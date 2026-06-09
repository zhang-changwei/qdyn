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


# -----------------------------------------------------------------------------
# Job progress
# -----------------------------------------------------------------------------


def _parse_nsw_from_incar(incar_path: Path) -> int | None:
    """Parse the NSW value from an INCAR file."""
    try:
        with open(incar_path, "r") as f:
            for line in f:
                stripped = line.strip().upper()
                if "NSW" in stripped:
                    # Handle formats like "NSW = 3000" or "NSW=3000"
                    parts = line.split("=")
                    if len(parts) >= 2:
                        try:
                            return int(parts[1].split()[0].strip())
                        except (ValueError, IndexError):
                            continue
    except OSError:
        pass
    return None


def _parse_nsw_from_text(text: str) -> int | None:
    """Parse the NSW value from INCAR text content."""
    for line in text.splitlines():
        stripped = line.strip().upper()
        if "NSW" in stripped:
            parts = line.split("=")
            if len(parts) >= 2:
                try:
                    return int(parts[1].split()[0].strip())
                except (ValueError, IndexError):
                    continue
    return None




def get_job_progress(
    manager: MainWorkflow, task_id: str, job_uuid: str
) -> JobProgressResponse:
    """
    Get the progress of a running or completed job.

    For NVT/NVE jobs, parses qdyn_md.log for MD step count and temperature.
    For SCF jobs, returns a basic available=True with step_type="scf".

    Uses a single ``jc.get_job_info()`` call to retrieve state, run_dir,
    and job name, then creates a ``RunDirAccess`` for file operations.
    """
    jc = manager._ensure_job_controller()
    try:
        job_info = jc.get_job_info(job_id=job_uuid)
    except Exception:
        return JobProgressResponse(available=False)

    if job_info is None:
        return JobProgressResponse(available=False)

    raw_state = job_info.state.value

    # Not started yet
    if raw_state in ("WAITING", "READY", "CHECKED_OUT"):
        return JobProgressResponse(available=False)

    access = _get_task_run_dir_access(manager, task_id, job_uuid)
    if access is None:
        return JobProgressResponse(available=False)

    # Extract job name from the same job_info object
    job_name = getattr(job_info, "name", "") or ""

    step_type = _detect_step_type(job_name, access.run_dir_path)

    if step_type in ("nvt", "nve"):
        return _get_md_progress(access, step_type)
    elif step_type in ("scf", "fused_scf_prenamd"):
        return _get_scf_progress(access)
    elif step_type == "fused_cat":
        return JobProgressResponse(
            available=True, step_type="fused_cat"
        )
    else:
        return JobProgressResponse(available=False, step_type=step_type)


def infer_md_total_steps(
    access: RunDirAccess, software: str | None = None
) -> int | None:
    """Infer MD total steps from the run directory.

    VASP compatibility fallback: reads ``NSW`` from ``INCAR`` when the
    ``qdyn_md.log`` header does not provide total steps.  Other software
    backends do not have an equivalent fallback yet.

    Args:
        access: Run directory accessor.
        software: DFT software identifier (e.g. ``"vasp"``).  ``None``
            falls back to checking for ``INCAR`` (VASP compatibility).

    Returns:
        Total MD steps or ``None`` if not determinable.
    """
    if software is not None and software != "vasp":
        return None
    try:
        if access.root_file_exists("INCAR"):
            incar_text = access.read_root_text("INCAR")
            return _parse_nsw_from_text(incar_text)
    except Exception:
        pass
    return None


def _get_md_progress(access: RunDirAccess, step_type: str) -> JobProgressResponse:
    """Parse qdyn_md.log for MD progress (step, temperature, energy)."""
    from ..output_postprocess import parse_qdyn_log_text

    current_step = 0
    total_steps: int | None = None
    last_temp: float | None = None
    last_energy: float | None = None

    try:
        if access.root_file_exists("qdyn_md.log"):
            data = parse_qdyn_log_text(access.read_root_text("qdyn_md.log"))
            current_step = data['steps'][-1]
            total_steps = data['total_steps']
            last_temp = data['temperatures'][-1]
            last_energy = data['potential_energies'][-1]
    except Exception as exc:
        logger.warning(
            "Failed to read qdyn_md.log from %s: %s", access.run_dir_path, exc
        )

    if total_steps is None:
        total_steps = infer_md_total_steps(access)

    percent: float | None = None
    if total_steps and total_steps > 0:
        percent = round(current_step / total_steps * 100, 2)

    return JobProgressResponse(
        available=True,
        step_type=step_type,
        current_step=current_step,
        total_steps=total_steps,
        percent=percent,
        last_temp=last_temp,
        last_energy=last_energy,
    )


def _parse_qdyn_scf_log_text(
    log_text: str,
) -> tuple[int, list[tuple[int, str, str]]]:
    """Parse qdyn_scf.log text into total steps and data records.

    Delegates to the core parser in ``output_postprocess``.
    """
    from ..output_postprocess import parse_qdyn_scf_log_text

    return parse_qdyn_scf_log_text(log_text)


_SCF_COMPLETED_LOG_CATEGORIES = {"normal", "posthamgnn", "overlap"}
_SCF_RUNNING_LOG_CATEGORIES = {"prehamgnn", "hamgnn"}


def _parse_scf_global_index(frame_name: str) -> int:
    """Extract the numeric index from an scf_* frame name."""
    try:
        return int(frame_name.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        return 0


def _get_scf_progress_from_log_text(log_text: str) -> JobProgressResponse:
    """Build SCF progress from qdyn_scf.log categories.

    Frames with a completed category (normal/posthamgnn/overlap) are ENDED.
    Frames with only intermediate categories (prehamgnn/hamgnn) are RUNNING.
    ENDED takes priority over RUNNING for the same frame.
    Frames with no log record are PENDING.
    """
    total_steps, records = _parse_qdyn_scf_log_text(log_text)

    # Reduce records to per-frame final status: ENDED > RUNNING.
    frame_status: dict[str, str] = {}
    for _, global_idx, category in records:
        if category in _SCF_COMPLETED_LOG_CATEGORIES:
            frame_status[global_idx] = "ENDED"
        elif category in _SCF_RUNNING_LOG_CATEGORIES:
            if frame_status.get(global_idx) != "ENDED":
                frame_status[global_idx] = "RUNNING"

    completed = sum(1 for s in frame_status.values() if s == "ENDED")
    running_frames = [idx for idx, s in frame_status.items() if s == "RUNNING"]
    running = len(running_frames)
    pending = max(0, total_steps - completed - running)
    percent = (
        round(completed / total_steps * 100, 2)
        if total_steps > 0
        else None
    )

    batch_info = SCFBatchInfo(
        completed=completed,
        converged=completed,
        failed=0,
        running=running,
        pending=pending,
    )

    current_frame: SCFCurrentFrame | None = None
    if running_frames:
        # Use the last RUNNING frame (preserving log order).
        last_running = running_frames[-1]
        current_frame = SCFCurrentFrame(
            name=last_running,
            global_index=_parse_scf_global_index(last_running),
            status="RUNNING",
            electronic_step_current=None,
            electronic_step_limit=None,
            scf_algorithm=None,
            converged=None,
        )

    return JobProgressResponse(
        available=True,
        step_type="scf",
        current_step=completed,
        total_steps=total_steps,
        percent=percent,
        batch=batch_info,
        current_frame=current_frame,
        failed_frames=[],
    )


def _get_scf_progress_from_status_scan(
    access: RunDirAccess,
) -> JobProgressResponse:
    """Get SCF batch progress from log-derived status scan.

    Fallback used when qdyn_scf.log is absent or unreadable.  The scan
    itself is also log-only; frames without a log record are PENDING.
    """
    scf_map = access.scan_scf_status()
    if not scf_map:
        return JobProgressResponse(available=True, step_type="scf", current_step=0)

    total = len(scf_map)
    completed = 0  # ENDED
    running = 0  # RUNNING
    running_subdir: str | None = None

    for subdir_name, info in scf_map.items():
        if info.status == "ENDED":
            completed += 1
        elif info.status == "RUNNING":
            running += 1
            running_subdir = subdir_name

    pending = max(0, total - completed - running)
    current_step = completed
    percent = round(current_step / total * 100, 2) if total > 0 else None

    batch_info = SCFBatchInfo(
        completed=completed,
        converged=completed,
        failed=0,
        running=running,
        pending=pending,
    )

    current_frame: SCFCurrentFrame | None = None
    if running_subdir is not None:
        frame_name = running_subdir
        global_index = 0
        try:
            global_index = int(frame_name.split("_", 1)[1])
        except (ValueError, IndexError):
            pass
        current_frame = SCFCurrentFrame(
            name=frame_name,
            global_index=global_index,
            status="RUNNING",
            electronic_step_current=None,
            electronic_step_limit=None,
            scf_algorithm=None,
            converged=None,
        )

    return JobProgressResponse(
        available=True,
        step_type="scf",
        current_step=current_step,
        total_steps=total,
        percent=percent,
        batch=batch_info,
        current_frame=current_frame,
        failed_frames=[],
    )


def _get_scf_progress(access: RunDirAccess) -> JobProgressResponse:
    """Get SCF batch progress with qdyn_scf.log as the primary source.

    If qdyn_scf.log exists and parses successfully, returns log-derived
    progress directly.  Falls back to a log-based status scan when the log
    is absent or unreadable (scan itself also uses log categories only).
    """
    try:
        if access.root_file_exists("qdyn_scf.log"):
            return _get_scf_progress_from_log_text(
                access.read_root_text("qdyn_scf.log")
            )
    except Exception as exc:
        logger.warning(
            "Failed to parse qdyn_scf.log from %s: %s",
            access.run_dir_path,
            exc,
        )

    return _get_scf_progress_from_status_scan(access)


# -----------------------------------------------------------------------------
# Job images
# -----------------------------------------------------------------------------


def get_job_images(
    manager: MainWorkflow, task_id: str, job_uuid: str
) -> JobImagesResponse:
    """
    Get result images for a completed job.

    Reads the 'images' field from the job's stored output and verifies
    that each file still exists via RunDirAccess (works for both local
    and remote workers).
    """
    try:
        raw_state = manager.get_job_status(job_uuid)
    except Exception:
        return JobImagesResponse(available=False)

    if raw_state != "COMPLETED":
        return JobImagesResponse(available=False)

    # Get job output from jobstore
    try:
        output = manager.get_job_output(job_uuid)
    except Exception:
        return JobImagesResponse(available=False)

    if output is None:
        return JobImagesResponse(available=True)

    image_paths = output.get("images") or []
    if not image_paths:
        return JobImagesResponse(available=True)

    # Get RunDirAccess to verify file existence
    access = _get_task_run_dir_access(manager, task_id, job_uuid)

    items: List[JobImageItem] = []
    for img_path in image_paths:
        basename = Path(img_path).name

        # Verify file exists in run_dir root
        exists = False
        if access is not None:
            try:
                exists = access.root_file_exists(basename)
            except Exception:
                pass

        if exists:
            url = f"/frontend/tasks/{task_id}/jobs/{job_uuid}/files/{basename}"
            items.append(JobImageItem(name=basename, url=url))

    return JobImagesResponse(available=True, images=items)


# -----------------------------------------------------------------------------
# MD Timeseries
# -----------------------------------------------------------------------------


def _parse_incar_numeric_value(incar_path: Path, key: str) -> float | None:
    """Parse a numeric value from an INCAR file using exact key matching.

    Uses a regex anchor so that e.g. ``key='NELM'`` does **not** match
    ``NELMIN``.
    """
    import re

    pattern = re.compile(
        rf'^\s*{re.escape(key)}\s*=\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)',
        re.IGNORECASE,
    )
    try:
        with open(incar_path, 'r') as f:
            for line in f:
                m = pattern.match(line)
                if m:
                    return float(m.group(1))
    except OSError:
        pass
    return None


def _resolve_md_attempt_files(
    run_dir: Path,
    step_type: str,
    attempt: int | None,
) -> tuple[Path, Path | None, int, list[MDAttemptItem]]:
    """Discover NVT retry attempt directories and resolve source directories.

    Returns
    -------
    tuple of (attempt_dir, incar_path_or_None, selected_attempt, attempts_list)
    """
    # Discover nvt_attempt_* directories
    attempt_dirs: list[Path] = sorted(
        run_dir.glob("nvt_attempt_*"),
        key=lambda p: int(p.name.split("_")[-1]) if p.name.split("_")[-1].isdigit() else 0,
    )

    # Build attempt list. All valid archived directories count for numbering,
    # but only attempts with qdyn_md.log can be selected for timeseries data.
    attempts: list[MDAttemptItem] = []
    max_archived = 0
    for d in attempt_dirs:
        if not d.is_dir():
            continue
        try:
            num = int(d.name.split("_")[-1])
        except ValueError:
            continue
        max_archived = max(max_archived, num)
        if (d / "qdyn_md.log").is_file():
            attempts.append(MDAttemptItem(
                attempt=num,
                label=f"Attempt {num}",
                is_current=False,
                archived=True,
            ))

    # The root-directory qdyn_md.log is the "current / latest" attempt
    current_num = max_archived + 1
    root_qdyn_log = run_dir / "qdyn_md.log"
    if root_qdyn_log.is_file():
        attempts.append(MDAttemptItem(
            attempt=current_num,
            label=f"Attempt {current_num} (latest)" if attempts else f"Attempt {current_num}",
            is_current=True,
            archived=False,
        ))

    # Determine which attempt to serve
    if attempt is None:
        # Default: latest (root directory)
        selected = current_num
    else:
        selected = attempt

    # Resolve paths for the selected attempt
    if selected == current_num and root_qdyn_log.is_file():
        attempt_dir = run_dir
        incar_path = (run_dir / "INCAR") if (run_dir / "INCAR").is_file() else None
    else:
        attempt_dir = run_dir / f"nvt_attempt_{selected}"
        qdyn_log_path = attempt_dir / "qdyn_md.log"
        if not qdyn_log_path.is_file():
            raise FileNotFoundError(
                f"qdyn_md.log not found for attempt {selected} "
                f"(looked in {attempt_dir})."
            )
        incar_path = (attempt_dir / "INCAR") if (attempt_dir / "INCAR").is_file() else None

    return attempt_dir, incar_path, selected, attempts


def _sample_series(series: dict, max_points: int) -> dict:
    """Down-sample series data using fixed-bucket min/max to preserve extremes.

    For each bucket the point with the minimum and maximum temperature value
    is kept, preserving peaks and troughs.  The result has at most
    ``2 * num_buckets`` points (may be slightly less due to deduplication).
    """
    n = len(series['steps'])
    if n <= max_points:
        return series

    # Reserve 2 slots for first/last points, rest goes to buckets
    num_buckets = (max_points - 2) // 2
    if num_buckets < 1:
        num_buckets = 1
    bucket_size = n / num_buckets

    indices: list[int] = [0]  # Always include the first point
    for b in range(num_buckets):
        start = int(b * bucket_size)
        end = int((b + 1) * bucket_size)
        if start >= n:
            break
        end = min(end, n)

        # Find min/max temperature indices within bucket
        min_idx = start
        max_idx = start
        for i in range(start, end):
            if series['temperatures'][i] < series['temperatures'][min_idx]:
                min_idx = i
            if series['temperatures'][i] > series['temperatures'][max_idx]:
                max_idx = i

        # Add in order to preserve temporal sequence
        if min_idx <= max_idx:
            indices.append(min_idx)
            if max_idx != min_idx:
                indices.append(max_idx)
        else:
            indices.append(max_idx)
            if min_idx != max_idx:
                indices.append(min_idx)

    # Always include the very last point
    if indices and indices[-1] != n - 1:
        indices.append(n - 1)

    # Deduplicate while preserving order
    seen: set[int] = set()
    unique: list[int] = []
    for idx in indices:
        if idx not in seen:
            seen.add(idx)
            unique.append(idx)

    sampled: dict = {}
    for key, arr in series.items():
        sampled[key] = [arr[i] for i in unique]
    return sampled


def _calc_energy_drift_slope(
    steps: list[int], total_energies: list[float]
) -> float | None:
    """Compute linear regression slope (eV/step) for total energy drift.

    Uses real ionic step numbers as the independent variable so the slope
    has correct physical units regardless of sampling.
    """
    n = len(total_energies)
    if n < 2 or len(steps) != n:
        return None
    mean_x = sum(steps) / n
    mean_y = sum(total_energies) / n
    ss_xy = 0.0
    ss_xx = 0.0
    for x, y in zip(steps, total_energies):
        dx = x - mean_x
        ss_xy += dx * (y - mean_y)
        ss_xx += dx * dx
    if ss_xx == 0:
        return 0.0
    return ss_xy / ss_xx


def _build_md_references(
    step_type: str,
    incar_path: Path | None,
    series: dict,
) -> MDReferenceLines:
    """Assemble reference line data for the chart."""
    potim: float | None = None
    tebeg: float | None = None
    teend: float | None = None

    if incar_path is not None:
        potim = _parse_incar_numeric_value(incar_path, "POTIM")
        if step_type == "nvt":
            tebeg = _parse_incar_numeric_value(incar_path, "TEBEG")
            teend = _parse_incar_numeric_value(incar_path, "TEEND")

    target_temp: float | None = None
    tol_low: float | None = None
    tol_high: float | None = None
    if step_type == "nvt" and teend is not None:
        target_temp = teend
        tol_low = teend * 0.9
        tol_high = teend * 1.1

    mean_total: float | None = None
    initial_total: float | None = None
    drift: float | None = None
    total_e = series.get('total_energies', [])
    if total_e:
        mean_total = sum(total_e) / len(total_e)
        initial_total = total_e[0]
        if step_type == "nve":
            drift = _calc_energy_drift_slope(series.get('steps', []), total_e)

    return MDReferenceLines(
        potim_fs=potim,
        tebeg=tebeg,
        teend=teend,
        target_temperature=target_temp,
        temperature_tolerance_low=tol_low,
        temperature_tolerance_high=tol_high,
        mean_total_energy=mean_total,
        initial_total_energy=initial_total,
        energy_drift_slope_ev_per_step=drift,
    )


def get_job_md_timeseries(
    manager: MainWorkflow,
    task_id: str,
    job_uuid: str,
    attempt: int | None,
    max_points: int,
) -> JobMdTimeseriesResponse:
    """Build the full MD timeseries response for a job.

    This is the main entry point called by the router.

    Resolution order depends on step_type:

    **NVE**: read ``run_dir/qdyn_md.log`` written by MDProgressMonitor.

    **NVT**: resolve selected attempt via ``_resolve_md_attempt_files()``
    first (preserves retry history), then read ``qdyn_md.log`` from the
    selected attempt directory.

    For remote workers, full timeseries parsing requires transferring large
    files.  Phase 1 returns ``available=False`` with a warning for remote
    workers; Phase 2 will implement streaming/chunked transfer.
    """
    from ..output_postprocess import parse_md_data_from_qdyn_log

    # --- Resolve run_dir and step_type ---
    jc = manager._ensure_job_controller()
    try:
        job_info = jc.get_job_info(job_id=job_uuid)
    except Exception:
        return JobMdTimeseriesResponse(available=False, warning="Failed to query job info.")

    if job_info is None:
        return JobMdTimeseriesResponse(available=False, warning="Job not found.")

    raw_state = job_info.state.value
    job_name = getattr(job_info, "name", "") or ""
    raw_run_dir = getattr(job_info, "run_dir", None)
    if not raw_run_dir:
        return JobMdTimeseriesResponse(available=False, warning="Job run directory not available yet.")

    # Check if this is a remote worker -- graceful fallback for Phase 1
    if manager.get_task_pool(task_id).remote:
        return JobMdTimeseriesResponse(
            available=False,
            step_type=_detect_step_type(job_name, str(raw_run_dir)),
            state=raw_state,
            warning=(
                "MD timeseries is not yet supported for remote workers. "
                "This feature will be available in a future update."
            ),
        )

    run_dir = Path(str(raw_run_dir))
    if not run_dir.is_dir():
        return JobMdTimeseriesResponse(available=False, warning="Job run directory does not exist.")

    step_type = _detect_step_type(job_name, str(run_dir))
    if step_type not in ("nvt", "nve"):
        return JobMdTimeseriesResponse(
            available=False,
            step_type=step_type,
            warning=f"MD timeseries not applicable for step_type '{step_type}'.",
        )

    # --- Parse MD data: strategy depends on step_type ---
    raw_data: dict | None = None
    incar_path: Path | None = None
    selected_attempt: int | None = None
    attempts: list[MDAttemptItem] = []

    if step_type == "nve":
        # NVE: only root qdyn_md.log is supported for timeseries data.
        qdyn_log_path = run_dir / "qdyn_md.log"
        selected_attempt = 1
        attempts = [
            MDAttemptItem(
                attempt=1, label="Attempt 1", is_current=True, archived=False,
            ),
        ]
        if (run_dir / "INCAR").is_file():
            incar_path = run_dir / "INCAR"
        try:
            raw_data = parse_md_data_from_qdyn_log(qdyn_log_path)
        except (FileNotFoundError, ValueError) as exc:
            return JobMdTimeseriesResponse(
                available=False,
                step_type=step_type,
                state=raw_state,
                selected_attempt=selected_attempt,
                attempts=attempts,
                warning=str(exc),
            )
    else:
        # NVT: resolve selected attempt directory, then parse qdyn_md.log.
        try:
            attempt_dir, incar_path, selected_attempt, attempts = (
                _resolve_md_attempt_files(run_dir, step_type, attempt)
            )
        except FileNotFoundError as exc:
            return JobMdTimeseriesResponse(
                available=False,
                step_type=step_type,
                state=raw_state,
                warning=str(exc),
            )

        # Within the selected attempt dir, read qdyn_md.log only.
        attempt_qdyn_log = attempt_dir / "qdyn_md.log"
        try:
            raw_data = parse_md_data_from_qdyn_log(attempt_qdyn_log)
        except (FileNotFoundError, ValueError) as exc:
            return JobMdTimeseriesResponse(
                available=False,
                step_type=step_type,
                state=raw_state,
                selected_attempt=selected_attempt,
                attempts=attempts,
                warning=str(exc),
            )

    original_points = len(raw_data['steps'])

    # --- Build time_fs ---
    potim: float | None = None
    if incar_path is not None:
        potim = _parse_incar_numeric_value(incar_path, "POTIM")

    if potim is not None and potim > 0:
        time_fs = [s * potim for s in raw_data['steps']]
    elif 'time_ps' in raw_data:
        # INCAR absent or POTIM missing — use qdyn_md.log time column (ps -> fs)
        time_fs = [t * 1000.0 for t in raw_data['time_ps']]
    else:
        # Ultimate fallback: use step number directly
        time_fs = [float(s) for s in raw_data['steps']]

    series_dict = {
        'steps': raw_data['steps'],
        'time_fs': time_fs,
        'temperatures': raw_data['temperatures'],
        'total_energies': raw_data['total_energies'],
        'potential_energies': raw_data['potential_energies'],
        'kinetic_energies': raw_data['kinetic_energies'],
        'converged': raw_data['converged'],
    }

    # --- References (computed on full data BEFORE sampling) ---
    references = _build_md_references(step_type, incar_path, series_dict)

    # --- Sampling ---
    sampled = original_points > max_points
    if sampled:
        series_dict = _sample_series(series_dict, max_points)

    returned_points = len(series_dict['steps'])
    # Override potim from the one we already parsed
    if potim is not None:
        references.potim_fs = potim

    # --- NSW / total_steps ---
    total_steps: int | None = None
    if incar_path is not None:
        nsw_val = _parse_incar_numeric_value(incar_path, "NSW")
        if nsw_val is not None:
            total_steps = int(nsw_val)
    # If INCAR is missing but qdyn_md.log header has total info, derive NSW
    if total_steps is None:
        total_from_header = raw_data.get('total_steps', 0)
        if total_from_header > 0:
            total_steps = total_from_header

    stats = MDTimeseriesStats(
        current_step=raw_data['steps'][-1] if raw_data['steps'] else 0,
        total_steps=total_steps,
        original_points=original_points,
        returned_points=returned_points,
        sampled=sampled,
    )

    series = MDSeriesData(**series_dict)

    return JobMdTimeseriesResponse(
        available=True,
        step_type=step_type,
        state=raw_state,
        selected_attempt=selected_attempt,
        attempts=attempts,
        series=series,
        references=references,
        stats=stats,
    )


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
