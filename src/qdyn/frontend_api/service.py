"""
Service layer for frontend API.

This module provides business logic functions for the frontend API layer,
including status derivation, job info retrieval, and task summaries.
All functions that need MainWorkflow access receive it via dependency
injection (manager_getter) to avoid circular imports with app.py.
"""

import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Union

from ..calc_common import read_strus
from ..database import qdyndb
from ..main_workflow import MainWorkflow, QueryError
from ._common import (
    _detect_step_type,
    _dt_str,
    _get_task_run_dir_access,
)
from .files import (
    build_download_zip,
    get_job_images,
    list_job_files,
    list_subdir_files,
    serve_job_file,
    serve_subdir_file,
)
from .job_inputs import (
    _flatten_parameter_mapping,
    get_job_input_params,
)
from .md_timeseries import get_job_md_timeseries
from .progress import (
    _get_scf_progress,
    _get_scf_progress_from_log_text,
    get_job_progress,
    infer_md_total_steps,
)
from .run_dir_access import (
    FileInfo,
    LocalRunDirAccess,
    RunDirAccess,
)
from .models import (
    JobErrorResponse,
    JobFileItem,
    JobImageItem,
    JobImagesResponse,
    JobInputParamsResponse,
    JobMdTimeseriesResponse,
    JobProgressResponse,
    JobStatusItem,
    ZipDownloadFileItem,
    MDAttemptItem,
    MDReferenceLines,
    MDSeriesData,
    MDTimeseriesStats,
    SCFBatchInfo,
    SCFCurrentFrame,
    SubdirInfo,
    TaskJobsStatusResponse,
    TaskSummary,
)

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Status derivation constants
# -----------------------------------------------------------------------------

# All running intermediate states from jobflow-remote
RUNNING_RAW_STATES = {
    "SUBMITTED",
    "CHECKED_OUT",
    "UPLOADED",
    "BATCH_SUBMITTED",
    "BATCH_RUNNING",
    "RUNNING",
    "RUN_FINISHED",
    "DOWNLOADED",
}

PAUSED_RAW_STATES = {"PAUSED"}

STOPPED_RAW_STATES = {"STOPPED", "USER_STOPPED"}

PENDING_RAW_STATES = {"READY", "WAITING"}

ERROR_RAW_STATES = {"REMOTE_ERROR", "ERROR"}


# -----------------------------------------------------------------------------
# Status derivation functions
# -----------------------------------------------------------------------------


def derive_task_status(raw_counts: Dict[str, int]) -> str:
    """
    Derive a task-level status from raw state counts.

    The derivation follows a priority hierarchy:
    1. ERROR / REMOTE_ERROR -> "ERROR"
    2. FAILED -> "FAILED"
    3. Any running intermediate state -> "RUNNING"
    4. STOPPED / USER_STOPPED -> "STOPPED"
    5. PAUSED -> "PAUSED"
    6. READY / WAITING or unknown states -> "PENDING"
    7. All COMPLETED -> "COMPLETED"

    Args:
        raw_counts: A dictionary mapping raw state strings to their counts.

    Returns:
        A derived status string: "RUNNING" | "FAILED" | "COMPLETED" | "PENDING" | "PAUSED" | "STOPPED" | "ERROR"
    """
    # Priority 1: Error states
    if any(raw_counts.get(state, 0) > 0 for state in ERROR_RAW_STATES):
        return "ERROR"

    # Priority 2: Failed
    if raw_counts.get("FAILED", 0) > 0:
        return "FAILED"

    # Priority 3: Running intermediate states
    if any(raw_counts.get(state, 0) > 0 for state in RUNNING_RAW_STATES):
        return "RUNNING"

    # Priority 4: Stopped states
    if any(raw_counts.get(state, 0) > 0 for state in STOPPED_RAW_STATES):
        return "STOPPED"

    # Priority 5: Paused states
    if any(raw_counts.get(state, 0) > 0 for state in PAUSED_RAW_STATES):
        return "PAUSED"

    # Priority 5: Pending states
    if any(raw_counts.get(state, 0) > 0 for state in PENDING_RAW_STATES):
        return "PENDING"

    # Check for unknown states (treat as pending)
    nonzero_states = {state for state, count in raw_counts.items() if count > 0}
    if nonzero_states and nonzero_states != {"COMPLETED"}:
        return "PENDING"

    # Priority 6: All completed
    return "COMPLETED"


def derive_job_state(raw_state: str) -> str:
    """
    Map a jobflow-remote raw state to a UI-friendly derived state.

    Args:
        raw_state: The raw state string from jobflow-remote JobInfo.state.

    Returns:
        A derived status string: "RUNNING" | "COMPLETED" | "FAILED" | "PENDING" | "PAUSED" | "STOPPED" | "ERROR"
    """
    if raw_state in ERROR_RAW_STATES:
        return "ERROR"
    if raw_state == "FAILED":
        return "FAILED"
    if raw_state in RUNNING_RAW_STATES:
        return "RUNNING"
    if raw_state in STOPPED_RAW_STATES:
        return "STOPPED"
    if raw_state in PAUSED_RAW_STATES:
        return "PAUSED"
    if raw_state == "COMPLETED":
        return "COMPLETED"
    return "PENDING"


# -----------------------------------------------------------------------------
# Job info retrieval functions
# -----------------------------------------------------------------------------


def get_job_info_safe(
    task_id: str,
    job_uuid: str,
    manager_getter: Callable[[], MainWorkflow],
) -> JobStatusItem:
    """
    Safely retrieve job information through an injected manager getter.

    This function uses dependency injection to access MainWorkflow,
    avoiding circular imports with app.py.

    Args:
        task_id: The task identifier (for context/validation).
        job_uuid: The job UUID to query.
        manager_getter: A callable that returns the MainWorkflow instance.

    Returns:
        A JobStatusItem containing the job's status information.

    Raises:
        QueryError: If the job cannot be found or queried.
    """
    manager = manager_getter()
    ji = manager.get_job_info(job_uuid)
    raw_state = ji.state.value

    # Get job metadata from database to retrieve name and index
    job_ids = qdyndb.get_task_job_ids(task_id)

    # Find the job's name and index by searching through steps
    job_name = job_uuid  # Default to uuid if name not found
    job_index = 0

    for step_name, uuid_list in job_ids.items():
        if job_uuid in uuid_list:
            job_index = uuid_list.index(job_uuid)
            if (step_name == "fused_scf_prenamd"
                    and job_index == len(uuid_list) - 1):
                job_name = "cat_canac_outputs"
            else:
                job_name = f"{step_name}_{job_index}"
            break

    return JobStatusItem(
        uuid=job_uuid,
        name=job_name,
        state=raw_state,
        derived_state=derive_job_state(raw_state),
        index=job_index,
        created_on=_dt_str(getattr(ji, "created_on", None)),
        start_time=_dt_str(getattr(ji, "start_time", None)),
        end_time=_dt_str(getattr(ji, "end_time", None)),
    )


def get_job_error_summary(
    task_id: str,
    job_uuid: str,
    manager_getter: Callable[[], MainWorkflow] | None = None,
) -> str | None:
    """
    Get an error summary for a failed job.

    Args:
        task_id: The task identifier (for context).
        job_uuid: The job UUID to query.
        manager_getter: Optional callable that returns the MainWorkflow instance.
                       Currently unused but kept for API consistency.

    Returns:
        An error summary string, or None if no error info is available.

    Note:
        The current implementation is a placeholder. Full implementation
        requires investigation of jobflow-remote's error reporting mechanisms.
        See TODO below.
    """
    # TODO: Implement actual error retrieval
    # Options to explore:
    # 1. JobController.get_job_info() may include error fields
    # 2. Check if jobflow-remote stores error messages in the jobstore
    # 3. Query the JobInfo object for 'error' or 'exception' attributes
    #
    # For now, return a placeholder indicating the feature is not implemented.
    return None


def get_job_error_detail(
    task_id: str,
    job_uuid: str,
    manager_getter: Callable[[], MainWorkflow],
) -> JobErrorResponse:
    """
    Retrieve structured error details for a specific job.

    Queries jobflow-remote's JobInfo for the job's error traceback and
    extracts a human-readable message from the first line of the traceback.

    Args:
        task_id: The task identifier (for ownership validation context).
        job_uuid: The job UUID to query.
        manager_getter: A callable that returns the MainWorkflow instance.

    Returns:
        A JobErrorResponse with structured error information.
    """
    manager = manager_getter()
    jc = manager._ensure_job_controller()

    try:
        job_info = jc.get_job_info(job_id=job_uuid)
    except Exception as exc:
        # Real query failure (backend error, connection issue, etc.) should return 500
        # This is different from "job not found in task" which returns 404
        raise QueryError(f"Query failed for job '{job_uuid}': {exc}")

    if job_info is None:
        # This shouldn't happen if the query succeeded, but handle defensively
        raise QueryError(f"Job '{job_uuid}' not found during post-query verification.")

    raw_state = job_info.state.value

    # Check for error information in both remote.error and top-level error
    # Use nested getattr to safely handle job_info without a remote attribute
    error_traceback = getattr(getattr(job_info, "remote", None), "error", None) or getattr(job_info, "error", None)

    if not error_traceback:
        return JobErrorResponse(
            state=raw_state,
            available=False,
        )

    # Extract the first line of the traceback as the short message
    message = _extract_error_message(error_traceback)

    return JobErrorResponse(
        state=raw_state,
        available=True,
        message=message,
        traceback=error_traceback,
    )


def _extract_error_message(traceback_str: str) -> str:
    """
    Extract a short, human-readable error message from a traceback string.

    Looks for the last non-empty line of the traceback (typically the
    exception message), or falls back to the first non-empty line.

    Args:
        traceback_str: The full traceback string.

    Returns:
        A short error message string.
    """
    lines = traceback_str.strip().splitlines()
    # Try the last non-empty line first (the exception message line)
    for line in reversed(lines):
        stripped = line.strip()
        if stripped:
            return stripped
    # Fallback
    return traceback_str.strip()[:200]


# -----------------------------------------------------------------------------
# Task summary functions
# -----------------------------------------------------------------------------


def get_task_summary_list(
    username: str,
    manager_getter: Callable[[], MainWorkflow],
) -> List[TaskSummary]:
    """
    Get a list of task summaries for the specified user.

    Merges tasks that are already submitted (tracked in MongoDB via
    jobflow-remote) with tasks that are still in the waiting queue
    (tracked in SQLite ``queued_submissions`` table).

    Args:
        username: The username to query tasks for.
        manager_getter: A callable that returns the MainWorkflow instance.

    Returns:
        A list of TaskSummary objects for the user's tasks.
    """
    task_ids = qdyndb.get_user_tasks(username)
    summaries = []

    # Collect queue-tracked task IDs so we can annotate or skip them.
    # Include QUEUED/DISPATCHING (active) and FAILED/CANCELLED (terminal)
    # queue entries.  Without this, FAILED/CANCELLED queue tasks would
    # fall through to _build_task_summary() which finds zero jobs and
    # derive_task_status({}) would incorrectly return COMPLETED.
    queued_entries = qdyndb.list_queued_for_user(username)
    queued_map: Dict[str, dict] = {}
    for entry in queued_entries:
        if entry["status"] in ("QUEUED", "DISPATCHING", "FAILED", "CANCELLED"):
            queued_map[entry["task_id"]] = entry

    # Fix: If a queue entry is FAILED but the task already has real jobs
    # in task_owners (i.e. update_task_dispatch_info succeeded before
    # mark_submitted failed), the flow was actually submitted to jf-remote.
    # In that case, remove from queued_map so the task is rendered via the
    # normal _build_task_summary() path — otherwise the real running task
    # would be masked by a misleading "queue FAILED" summary.
    failed_but_submitted = []
    for tid, entry in queued_map.items():
        if entry["status"] == "FAILED":
            real_job_ids = qdyndb.get_task_job_ids(tid)
            if real_job_ids:
                failed_but_submitted.append(tid)
    for tid in failed_but_submitted:
        del queued_map[tid]

    # Compute global queue positions (1-based) across all users
    all_queued = qdyndb.list_all_queued()
    queue_positions: Dict[str, int] = {
        q["task_id"]: i + 1 for i, q in enumerate(all_queued)
    }

    for task_id in task_ids:
        if task_id in queued_map:
            # Task is still in the waiting queue — build a lightweight summary
            # without querying MongoDB (the flow hasn't been submitted yet).
            summary = _build_queued_task_summary(
                task_id, username, queued_map[task_id], queue_positions
            )
        else:
            summary = _build_task_summary(task_id, manager_getter)
        if summary is not None:
            summaries.append(summary)

    return summaries


def _build_queued_task_summary(
    task_id: str,
    username: str,
    queue_entry: dict,
    queue_positions: Dict[str, int],
) -> TaskSummary:
    """Build a TaskSummary for a task that is still in the waiting queue.

    These tasks have not been submitted to jobflow-remote yet, so there
    are no MongoDB records to query.  The summary is constructed from
    the SQLite ``queued_submissions`` and ``task_owners`` tables only.
    """
    import time as _time
    from datetime import datetime, timezone

    meta = qdyndb.get_task_metadata(task_id) or {}

    # Parse created_at from the queue entry (SQLite datetime string)
    created_at: float = _time.time()
    try:
        dt = datetime.strptime(
            queue_entry["created_at"], "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=timezone.utc)
        created_at = dt.timestamp()
    except Exception:
        pass

    queue_status = queue_entry["status"]  # QUEUED / DISPATCHING / FAILED / CANCELLED

    # Map queue-level status to a user-facing derived_status.
    # QUEUED and DISPATCHING are shown as-is; FAILED and CANCELLED queue
    # entries must surface the correct terminal state instead of falling
    # through to derive_task_status({}) which would return COMPLETED.
    _QUEUE_DERIVED_STATUS = {
        "QUEUED": "QUEUED",
        "DISPATCHING": "DISPATCHING",
        "FAILED": "FAILED",
        "CANCELLED": "CANCELLED",
    }
    derived_status = _QUEUE_DERIVED_STATUS.get(queue_status, queue_status)

    return TaskSummary(
        task_id=task_id,
        owner=username,
        created_at=created_at,
        raw_status_counts={},
        derived_status=derived_status,
        total_jobs=0,
        failed_job_names=[],
        steps=[],
        completed_steps=[],
        task_name=meta.get("task_name"),
        formula=meta.get("formula"),
        num_atoms=meta.get("num_atoms"),
        prev_task_id=meta.get("prev_task_id"),
        worker=meta.get("worker"),
        resume_next_step=None,
        resume_eligible=False,
        queue_status=queue_status,
        queue_position=queue_positions.get(task_id),
        pool_name=queue_entry.get("pool_name") or meta.get("pool_name"),
        runtime_worker=None,
    )


def get_task_detail(
    task_id: str,
    manager_getter: Callable[[], MainWorkflow],
) -> TaskJobsStatusResponse:
    """
    Get detailed status for all jobs under a task.

    Uses a single batch query via ``jc.get_jobs_info_query()`` instead of
    per-job ``get_job_info()`` calls, reducing Mongo round-trips from O(N)
    to O(1).

    Args:
        task_id: The task identifier to query.
        manager_getter: A callable that returns the MainWorkflow instance.

    Returns:
        A TaskJobsStatusResponse containing all job statuses.

    Raises:
        ValueError: If the task is not found.
    """
    owner = qdyndb.get_task_owner(task_id)
    if owner is None:
        raise ValueError(f"Task '{task_id}' not found")

    job_ids = qdyndb.get_task_job_ids(task_id)

    # --- Queue-aware early return ---
    # If the task is tracked in queued_submissions with a non-terminal-submitted
    # status, check whether the flow was actually submitted to jf-remote.
    # This handles two scenarios:
    #   1. QUEUED / DISPATCHING / CANCELLED: no real jobs, return queue status
    #   2. FAILED: may or may not have real jobs
    #      - If job_ids is non-empty, flow was submitted; fall through to
    #        normal detail logic (don't let queue FAILED mask real jobs)
    #      - If job_ids is empty, genuinely failed; return queue FAILED status
    queue_entry = qdyndb.get_queued_status(task_id)
    if queue_entry is not None:
        q_status = queue_entry["status"]
        if q_status in ("QUEUED", "DISPATCHING", "CANCELLED"):
            # No jobs submitted yet — return lightweight queue detail
            task_meta = qdyndb.get_task_metadata(task_id)
            prev_task_id = task_meta.get("prev_task_id") if task_meta else None
            return TaskJobsStatusResponse(
                task_id=task_id,
                raw_status_counts={},
                derived_status=q_status,
                jobs=[],
                prev_task_id=prev_task_id,
                task_name=task_meta.get("task_name") if task_meta else None,
                formula=task_meta.get("formula") if task_meta else None,
            )
        if q_status == "FAILED" and not job_ids:
            # Queue dispatch genuinely failed, no jobs in jf-remote
            task_meta = qdyndb.get_task_metadata(task_id)
            prev_task_id = task_meta.get("prev_task_id") if task_meta else None
            return TaskJobsStatusResponse(
                task_id=task_id,
                raw_status_counts={},
                derived_status="FAILED",
                jobs=[],
                prev_task_id=prev_task_id,
                task_name=task_meta.get("task_name") if task_meta else None,
                formula=task_meta.get("formula") if task_meta else None,
            )
        # For FAILED with real job_ids, or SUBMITTED: fall through to normal path

    # Collect all UUIDs across steps
    all_uuids: List[str] = []
    for uuid_list in job_ids.values():
        all_uuids.extend(uuid_list)

    # Batch-fetch all job infos in a single Mongo query
    uuid_to_job_info: Dict[str, object] = {}
    if all_uuids:
        try:
            manager = manager_getter()
            jc = manager._ensure_job_controller()
            job_infos = jc.get_jobs_info_query(
                query={"uuid": {"$in": all_uuids}}
            )
            # Keep only the highest-index record per UUID,
            # matching get_job_info()'s sort=[("index", DESC)] semantics.
            for ji in job_infos:
                existing = uuid_to_job_info.get(ji.uuid)
                if existing is None or getattr(ji, "index", 0) > getattr(existing, "index", 0):
                    uuid_to_job_info[ji.uuid] = ji
        except Exception:
            logger.warning(
                "Batch job info query failed for task %s, falling back to per-job queries",
                task_id,
            )

    # Assemble job status items
    jobs: List[JobStatusItem] = []
    raw_status_counts: Dict[str, int] = {}
    failed_job_names: List[str] = []

    for step_name, uuid_list in job_ids.items():
        for idx, job_uuid in enumerate(uuid_list):
            ji = uuid_to_job_info.get(job_uuid)
            if ji is not None:
                raw_state = ji.state.value
                derived = derive_job_state(raw_state)
                if (step_name == "fused_scf_prenamd"
                        and idx == len(uuid_list) - 1):
                    display_name = "cat_canac_outputs"
                else:
                    display_name = f"{step_name}_{idx}"
                job_item = JobStatusItem(
                    uuid=job_uuid,
                    name=display_name,
                    state=raw_state,
                    derived_state=derived,
                    index=idx,
                    created_on=_dt_str(getattr(ji, "created_on", None)),
                    start_time=_dt_str(getattr(ji, "start_time", None)),
                    end_time=_dt_str(getattr(ji, "end_time", None)),
                )
                jobs.append(job_item)
                raw_status_counts[raw_state] = raw_status_counts.get(raw_state, 0) + 1
                if derived == "FAILED":
                    failed_job_names.append(job_item.name)
            else:
                # Fallback: per-job query (batch query missed this UUID)
                try:
                    job_item = get_job_info_safe(task_id, job_uuid, manager_getter)
                    if (step_name == "fused_scf_prenamd"
                            and idx == len(uuid_list) - 1):
                        job_item.name = "cat_canac_outputs"
                    else:
                        job_item.name = f"{step_name}_{idx}"
                    job_item.index = idx
                    jobs.append(job_item)
                    raw_status_counts[job_item.state] = (
                        raw_status_counts.get(job_item.state, 0) + 1
                    )
                    if job_item.derived_state == "FAILED":
                        failed_job_names.append(job_item.name)
                except Exception:
                    jobs.append(
                        JobStatusItem(
                            uuid=job_uuid,
                            name=f"{step_name}_{idx}",
                            state="ERROR",
                            derived_state="ERROR",
                            error="Unable to query job status",
                            index=idx,
                        )
                    )
                    raw_status_counts["ERROR"] = raw_status_counts.get("ERROR", 0) + 1

    derived_status = derive_task_status(raw_status_counts)

    # Retrieve metadata (resume chain, task_name, formula)
    task_meta = qdyndb.get_task_metadata(task_id)
    prev_task_id = task_meta.get("prev_task_id") if task_meta else None

    return TaskJobsStatusResponse(
        task_id=task_id,
        raw_status_counts=raw_status_counts,
        derived_status=derived_status,
        jobs=jobs,
        prev_task_id=prev_task_id,
        task_name=task_meta.get("task_name") if task_meta else None,
        formula=task_meta.get("formula") if task_meta else None,
    )


# Canonical step orderings used for resume eligibility computation
_STEP_ORDER_NORMAL = ["nvt", "nve", "scf", "pre_namd", "namd"]
_STEP_ORDER_FUSED = ["nvt", "nve", "fused_scf_prenamd", "namd"]


def _get_step_order(job_ids: dict) -> list[str]:
    """Return the step ordering based on which steps exist."""
    if "fused_scf_prenamd" in job_ids:
        return _STEP_ORDER_FUSED
    return _STEP_ORDER_NORMAL


def _build_task_summary(
    task_id: str,
    manager_getter: Callable[[], MainWorkflow],
) -> TaskSummary | None:
    """
    Build a TaskSummary for a single task.

    Computes per-step completion status and resume eligibility so the
    frontend can drive the resume UI without additional queries.

    Args:
        task_id: The task identifier.
        manager_getter: A callable that returns the MainWorkflow instance.

    Returns:
        A TaskSummary object, or None if the task cannot be processed.
    """
    owner = qdyndb.get_task_owner(task_id)
    if owner is None:
        return None

    job_ids = qdyndb.get_task_job_ids(task_id)

    # Collect status counts and per-step completion info
    raw_status_counts: Dict[str, int] = {}
    total_jobs = 0
    failed_job_names: List[str] = []
    # Track per-step: whether all jobs in that step are COMPLETED
    step_all_completed: Dict[str, bool] = {}

    for step_name, uuid_list in job_ids.items():
        all_completed_for_step = True
        for idx, job_uuid in enumerate(uuid_list):
            total_jobs += 1
            try:
                manager = manager_getter()
                raw_state = manager.get_job_status(job_uuid)
                raw_status_counts[raw_state] = raw_status_counts.get(raw_state, 0) + 1

                if raw_state == "FAILED":
                    failed_job_names.append(f"{step_name}_{idx}")

                if raw_state != "COMPLETED":
                    all_completed_for_step = False

            except Exception:
                # Count unknown/query errors as ERROR
                raw_status_counts["ERROR"] = raw_status_counts.get("ERROR", 0) + 1
                all_completed_for_step = False

        step_all_completed[step_name] = all_completed_for_step

    # Sort steps by canonical order
    step_order = _get_step_order(job_ids)
    steps = [s for s in step_order if s in job_ids]

    # Compute completed_steps: contiguous prefix of fully-completed steps
    completed_steps: List[str] = []
    for s in steps:
        if step_all_completed.get(s, False):
            completed_steps.append(s)
        else:
            break  # stop at first incomplete step

    # Compute resume_next_step: the step right after the last completed one
    resume_next_step: str | None = None
    if completed_steps:
        last_completed = completed_steps[-1]
        last_idx = step_order.index(last_completed)
        if last_idx + 1 < len(step_order):
            resume_next_step = step_order[last_idx + 1]

    created_at = _get_task_created_at_fallback(task_id)
    derived_status = derive_task_status(raw_status_counts)

    # Resume eligibility: must have a valid next step, and the task must
    # have finished running (COMPLETED or FAILED).
    resume_eligible = (
        resume_next_step is not None
        and derived_status in ("COMPLETED", "FAILED")
    )

    # Fetch persisted metadata (formula, num_atoms, prev_task_id, worker)
    meta = qdyndb.get_task_metadata(task_id) or {}

    return TaskSummary(
        task_id=task_id,
        owner=owner,
        created_at=created_at,
        raw_status_counts=raw_status_counts,
        derived_status=derived_status,
        total_jobs=total_jobs,
        failed_job_names=failed_job_names,
        steps=steps,
        completed_steps=completed_steps,
        task_name=meta.get("task_name"),
        formula=meta.get("formula"),
        num_atoms=meta.get("num_atoms"),
        prev_task_id=meta.get("prev_task_id"),
        worker=meta.get("worker"),
        resume_next_step=resume_next_step,
        resume_eligible=resume_eligible,
        # Pool fields: queue_status/queue_position are None for submitted tasks
        pool_name=meta.get("pool_name"),
        runtime_worker=meta.get("worker"),
    )


def _get_task_created_at_fallback(task_id: str) -> float:
    """
    Get the creation timestamp for a task.

    This is a temporary implementation that queries the database directly.
    Ideally, QdynDB should have a dedicated method for this.

    Args:
        task_id: The task identifier.

    Returns:
        A Unix timestamp (seconds since epoch), or 0.0 if not found.
    """
    import time
    from datetime import datetime, timezone

    try:
        conn = qdyndb.get_db()
        row = conn.execute(
            "SELECT created_at FROM task_owners WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row:
            # SQLite datetime('now') stores UTC; parse with explicit UTC timezone
            dt = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
            return dt.timestamp()
    except Exception:
        pass

    # Fallback to current time if we can't parse
    return time.time()



# =============================================================================
# Structure Preview (on-demand computation)
# =============================================================================


def compute_structure_preview(
    task_id: str,
    manager: MainWorkflow,
    *,
    enrich_constraints: bool = True,
):
    """Compute structure preview on-demand for a task.

    Resolution order:
    1. Queued task: read input.stru + input.stru_format from queue payload
    2. Running/completed task: read structure file from first job's run directory
    3. Resume task with no own structure: trace prev_task_id chain (max 10 hops)

    After resolving the structure, if enrich_constraints is True and the preview
    has no file-level constraints, attempts to apply constraint_layers from the
    task's InputT (matching runtime semantics where file-level constraints take
    priority).

    Set enrich_constraints=False to get the raw preview with only file-level
    constraints (useful when the caller will apply its own layer parameters).

    Returns StructurePreviewPayload or None.
    """
    result = _try_preview_for_task(task_id, manager)
    if result is not None:
        if enrich_constraints:
            return _enrich_with_layer_constraints(result, task_id)
        return result

    # Trace prev_task_id chain for resume tasks (max 10 hops)
    task_meta = qdyndb.get_task_metadata(task_id)
    if task_meta and task_meta.get("prev_task_id"):
        visited: set = {task_id}
        tid = task_meta["prev_task_id"]
        for _ in range(10):
            if not tid or tid in visited:
                break
            visited.add(tid)
            result = _try_preview_for_task(tid, manager)
            if result is not None:
                if enrich_constraints:
                    return _enrich_with_layer_constraints(result, task_id)
                return result
            parent_meta = qdyndb.get_task_metadata(tid)
            if not parent_meta:
                break
            tid = parent_meta.get("prev_task_id")

    return None


def _enrich_with_layer_constraints(preview, task_id: str):
    """If preview has no file-level constraints, try to compute layer mask
    from the task's InputT constraint_layers parameters.

    Matches runtime semantics: file-level constraints always take priority.
    """
    if preview.constraint_mask is not None:
        # File already has constraints — use as-is
        return preview

    constraint_params = _get_constraint_params_for_task(task_id)
    if not constraint_params:
        return preview

    try:
        from copy import deepcopy

        from ..input import SelDynInputT
        from ..tools.seldyn import add_constraints

        # Reconstruct Atoms from preview data
        from ase import Atoms
        from .structure_preview import build_preview_from_atoms

        atoms = Atoms(
            symbols=preview.species,
            positions=preview.cart_coords,
            cell=preview.lattice,
            pbc=preview.pbc,
        )

        sel = SelDynInputT(
            constraint_layers=constraint_params["constraint_layers"],
            layer_direction=constraint_params["layer_direction"],
            total_layers=constraint_params["total_layers"],
        )
        atoms_copy = deepcopy(atoms)
        add_constraints(atoms_copy, sel)
        return build_preview_from_atoms(atoms_copy)
    except Exception:
        logger.debug(
            "Failed to compute layer constraints for task %s", task_id,
            exc_info=True,
        )

    return preview


def _get_constraint_params_for_task(task_id: str) -> dict | None:
    """Extract constraint_layers/layer_direction/total_layers from a task's
    InputT, trying queued payload first, then MongoDB job collection."""

    # Strategy 1: queued payload (for tasks that went through the queue)
    payload_json = qdyndb.get_queued_payload(task_id)
    if payload_json:
        try:
            payload = json.loads(payload_json)
            input_data = payload.get("input", {})
            result = _extract_constraint_params_from_input(input_data)
            if result:
                return result
        except Exception:
            logger.debug(
                "Failed to extract constraint params from queued payload for %s",
                task_id, exc_info=True,
            )

    # Strategy 2: MongoDB jobs collection, sorted by job index (first step first)
    try:
        from jobflow_remote.config.manager import ConfigManager

        cm = ConfigManager()
        project = cm.get_project()
        jc = project.get_job_controller()

        docs = jc.jobs.find(
            {"job.metadata.qdyn_task_id": task_id},
            {"job.function_kwargs.parameters": 1, "job.index": 1, "_id": 0},
        ).sort("job.index", 1)
        for doc in docs:
            params = (
                doc.get("job", {})
                .get("function_kwargs", {})
                .get("parameters", {})
            )
            if isinstance(params, dict):
                result = _extract_constraint_params_from_input(params)
                if result:
                    return result
    except Exception:
        logger.debug(
            "Failed to read constraint params from MongoDB for task %s",
            task_id, exc_info=True,
        )

    return None


def _extract_constraint_params_from_input(input_data: dict) -> dict | None:
    """Extract constraint params from an input dict (InputT or NVT/NVE sub-dict).

    Looks for the nested sel layout (sel.constraint_layers) at the top level
    or inside nvt_input / nve_input sub-dicts.

    constraint_layers may be list[int] (post-validator) or str (raw).
    Both are accepted and converted to str for downstream SelDynInputT construction.
    """
    def _try_extract(data: dict) -> dict | None:
        sel = data.get("sel")
        if not isinstance(sel, dict):
            return None
        cl = sel.get("constraint_layers")
        ld = sel.get("layer_direction")
        tl = sel.get("total_layers")
        if not cl or not ld or not tl:
            return None
        try:
            cl_str = " ".join(str(x) for x in cl) if isinstance(cl, list) else str(cl)
            return {
                "constraint_layers": cl_str,
                "layer_direction": str(ld),
                "total_layers": int(tl),
            }
        except (ValueError, TypeError):
            return None

    # Try nested sel at top level (direct NVT/NVE input dict)
    result = _try_extract(input_data)
    if result:
        return result

    # Try nested dicts (nvt_input / nve_input as sub-dicts of InputT)
    for step_key in ("nvt_input", "nve_input"):
        step_data = input_data.get(step_key)
        if isinstance(step_data, dict):
            result = _try_extract(step_data)
            if result:
                return result

    return None


def _try_preview_for_task(
    task_id: str,
    manager: MainWorkflow,
):
    """Attempt to build a structure preview for a single task.

    Tries queued payload first, then run directory of the first job.
    Returns None if neither source is available or parsing fails.
    """
    from .structure_preview import build_preview
    from ..params import STRU_FNAME_MAPPING, STRU_FORMAT_MAPPING, TRAJ_FORMAT_MAPPING

    # --- Strategy 1: Queued task payload ---
    payload_json = qdyndb.get_queued_payload(task_id)
    if payload_json:
        try:
            payload = json.loads(payload_json)
            input_data = payload.get("input", {})
            stru_text = input_data.get("stru", "")
            stru_format = input_data.get("stru_format", "vasp")

            if stru_text:
                return build_preview(stru_text, fmt=stru_format)

            # If stru is empty but stru_hash exists, read first frame from traj
            stru_hash = input_data.get("stru_hash", "")
            if stru_hash:
                preview = _preview_from_traj_hash(
                    stru_hash, stru_format, task_id, manager
                )
                if preview is not None:
                    return preview
        except Exception:
            logger.warning(
                "Failed to build preview from queued payload for task %s",
                task_id,
            )

    # --- Strategy 1b: Persisted stru_hash in task_owners ---
    # After dispatch, queued_submissions is purged but stru_hash survives
    # in task_owners (persisted at submit time).
    meta = qdyndb.get_task_metadata(task_id)
    if meta and meta.get("stru_hash"):
        fmt = meta.get("stru_format") or "vasp"
        preview = _preview_from_traj_hash(
            meta["stru_hash"], fmt, task_id, manager
        )
        if preview is not None:
            return preview

    # --- Strategy 2: First job's run directory ---
    job_ids = qdyndb.get_task_job_ids(task_id)
    if not job_ids:
        return None

    # Get the first step's first job UUID
    # Preserve step ordering based on canonical workflow order
    _STEP_ORDER_MAP = {
        "nvt": 0, "nve": 1, "scf": 2,
        "fused_scf_prenamd": 2, "fused_cat": 2,
        "pre_namd": 3, "namd": 4,
    }
    sorted_steps = sorted(
        job_ids.keys(),
        key=lambda s: _STEP_ORDER_MAP.get(s, 99),
    )
    first_job_uuid = None
    first_step = None
    for step in sorted_steps:
        uuids = job_ids[step]
        if uuids:
            first_job_uuid = uuids[0]
            first_step = step
            break

    if not first_job_uuid:
        return None

    access = _get_task_run_dir_access(manager, task_id, first_job_uuid)
    access_ok = access is not None and access.is_available()

    # Determine software from task payload or default to vasp
    software = _resolve_software_for_task(task_id, manager)

    # For NVT/NVE first steps: read the structure file from run dir
    if access_ok and first_step in ("nvt", "nve"):
        stru_filename = STRU_FNAME_MAPPING.get(software)
        if stru_filename and access.root_file_exists(stru_filename):
            try:
                content = access.read_root_text(stru_filename)
                # Determine ASE format from software
                fmt = STRU_FORMAT_MAPPING.get(software, software)
                return build_preview(content, fmt=fmt)
            except Exception:
                logger.warning(
                    "Failed to parse structure from %s in run dir for task %s",
                    stru_filename,
                    task_id,
                )

    # For SCF first step: try trajectory file or structure file
    if access_ok and first_step == "scf":
        # Try reading trajectory first frame from run dir
        from ..params import TRAJ_FNAME_MAPPING

        traj_filename = TRAJ_FNAME_MAPPING.get(software)
        if traj_filename and access.root_file_exists(traj_filename):
            try:
                content = access.read_root_text(traj_filename)
                ase_fmt = TRAJ_FORMAT_MAPPING.get(software, software)
                # build_preview reads first frame by default
                return build_preview(content, fmt=ase_fmt)
            except Exception:
                logger.warning(
                    "Failed to parse trajectory from %s for task %s",
                    traj_filename,
                    task_id,
                )

        # Fallback: try structure file in run dir
        stru_filename = STRU_FNAME_MAPPING.get(software)
        if stru_filename and access.root_file_exists(stru_filename):
            try:
                content = access.read_root_text(stru_filename)
                fmt = STRU_FORMAT_MAPPING.get(software, software)
                return build_preview(content, fmt=fmt)
            except Exception:
                pass

    # Generic fallback: try structure file regardless of step type
    if access_ok:
        stru_filename = STRU_FNAME_MAPPING.get(software)
        if stru_filename and access.root_file_exists(stru_filename):
            try:
                content = access.read_root_text(stru_filename)
                fmt = STRU_FORMAT_MAPPING.get(software, software)
                return build_preview(content, fmt=fmt)
            except Exception:
                pass

    # --- Strategy 3: Read traj_path from MongoDB job document ---
    # SCF jobs store their trajectory source path in function_kwargs.
    # This handles cases where the trajectory isn't in the run dir but
    # in a separate data directory (e.g. data/trajectory/{hash}).
    preview = _preview_from_job_kwargs(first_job_uuid, manager)
    if preview is not None:
        return preview

    return None


def _preview_from_job_kwargs(
    job_uuid: str,
    manager: MainWorkflow,
):
    """Extract structure data from MongoDB job document and build preview.

    Handles two cases:
    1. SCF jobs: function_kwargs contains traj_path → read trajectory first frame
    2. NVT/NVE jobs: function_kwargs contains structure (serialized ASE Atoms dict)

    This is the fallback when run directory is unavailable (e.g. remote worker,
    stopped task, or job that hasn't started yet).

    Returns StructurePreviewPayload or None.
    """
    from ase import Atoms

    from ..params import TRAJ_FORMAT_MAPPING
    from .structure_preview import build_preview_from_atoms

    try:
        jc = manager._ensure_job_controller()
        jobs_col = jc.db[jc.jobs_collection]
        doc = jobs_col.find_one(
            {"uuid": job_uuid},
            {"job.function_kwargs": 1},
        )
        if not doc:
            return None

        kwargs = doc.get("job", {}).get("function_kwargs", {})
        software = kwargs.get("software", "vasp")

        # --- Case 1: Serialized ASE Atoms dict (NVT/NVE jobs) ---
        stru_dict = kwargs.get("structure")
        if isinstance(stru_dict, dict) and "positions" in stru_dict:
            import numpy as np
            for key in stru_dict:
                if isinstance(stru_dict[key], list):
                    stru_dict[key] = np.array(stru_dict[key])
            atoms = Atoms.fromdict(stru_dict)
            return build_preview_from_atoms(atoms)

        # --- Case 2: Trajectory file path (SCF jobs) ---
        traj_path = kwargs.get("traj_path")
        traj_format = kwargs.get("traj_format", software)

        if traj_path:
            traj_path = Path(traj_path)
            if traj_path.is_file():
                ase_fmt = TRAJ_FORMAT_MAPPING.get(traj_format, traj_format)
                atoms = read_strus(ase_fmt, str(traj_path), first_only=True)[0]
                return build_preview_from_atoms(atoms)
    except Exception:
        logger.warning(
            "Failed to build preview from job kwargs for %s", job_uuid
        )
        return None


def _preview_from_traj_hash(
    stru_hash: str,
    stru_format: str,
    task_id: str,
    manager: MainWorkflow,
):
    """Read the first frame of a trajectory file identified by hash.

    Returns a StructurePreviewPayload or None on failure.
    """
    from ..params import TRAJ_FORMAT_MAPPING
    from .structure_preview import build_preview_from_atoms

    pool = manager.get_task_pool(task_id)
    traj_path = Path(pool.get_user_file_path('trajectory', stru_hash))
    if not traj_path.is_file():
        return None

    try:
        ase_fmt = TRAJ_FORMAT_MAPPING.get(stru_format, stru_format)
        atoms = read_strus(ase_fmt, str(traj_path), first_only=True)[0]
        return build_preview_from_atoms(atoms)
    except Exception:
        logger.warning(
            "Failed to parse trajectory hash %s for preview", stru_hash
        )
        return None


def _resolve_software_for_task(task_id: str, manager: MainWorkflow) -> str:
    """Determine the software used by a task.

    Scans step-specific inputs (nvt_input, nve_input, scf_input) for a
    ``software`` field.  Falls back to ``'vasp'`` when none is found.
    """
    payload_json = qdyndb.get_queued_payload(task_id)
    if payload_json:
        try:
            payload = json.loads(payload_json)
            input_data = payload.get("input", {})
            for section in ("nvt_input", "nve_input", "scf_input"):
                data = input_data.get(section)
                if isinstance(data, dict):
                    sw = data.get("software")
                    if sw:
                        return sw
        except Exception:
            pass
    return "vasp"
