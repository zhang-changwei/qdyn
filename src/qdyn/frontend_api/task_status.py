"""Task and job status derivation, summaries, and error reporting."""

import logging
from collections.abc import Callable

from ..database import qdyndb
from ..main_workflow import MainWorkflow, QueryError
from ..params import RUNNING_RAW_STATES, STEP_ORDER_FUSED, STEP_ORDER_NORMAL
from ._common import _dt_str
from .models import (
    JobErrorResponse,
    JobStatusItem,
    TaskJobsStatusResponse,
    TaskSummary,
)

logger = logging.getLogger(__name__)


PAUSED_RAW_STATES = {"PAUSED"}
STOPPED_RAW_STATES = {"STOPPED", "USER_STOPPED"}
PENDING_RAW_STATES = {"READY", "WAITING"}
ERROR_RAW_STATES = {"REMOTE_ERROR", "ERROR"}


def derive_task_status(raw_counts: dict[str, int]) -> str:
    """Derive a task-level status from raw state counts."""
    if any(raw_counts.get(state, 0) > 0 for state in ERROR_RAW_STATES):
        return "ERROR"
    if raw_counts.get("FAILED", 0) > 0:
        return "FAILED"
    if any(raw_counts.get(state, 0) > 0 for state in RUNNING_RAW_STATES):
        return "RUNNING"
    if any(raw_counts.get(state, 0) > 0 for state in STOPPED_RAW_STATES):
        return "STOPPED"
    if any(raw_counts.get(state, 0) > 0 for state in PAUSED_RAW_STATES):
        return "PAUSED"
    if any(raw_counts.get(state, 0) > 0 for state in PENDING_RAW_STATES):
        return "PENDING"
    nonzero_states = {state for state, count in raw_counts.items() if count > 0}
    if nonzero_states and nonzero_states != {"COMPLETED"}:
        return "PENDING"
    return "COMPLETED"


def derive_job_state(raw_state: str) -> str:
    """Map a jobflow-remote raw state to a UI-friendly derived state."""
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


def get_job_info_safe(
    task_id: str,
    job_uuid: str,
    manager_getter: Callable[[], MainWorkflow],
) -> JobStatusItem:
    """Safely retrieve job information through an injected manager getter."""
    manager = manager_getter()
    ji = manager.get_job_info(job_uuid)
    raw_state = ji.state.value

    job_ids = qdyndb.get_task_job_ids(task_id)

    job_name = job_uuid
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
    """Get an error summary for a failed job (placeholder)."""
    return None


def get_job_error_detail(
    task_id: str,
    job_uuid: str,
    manager_getter: Callable[[], MainWorkflow],
) -> JobErrorResponse:
    """Retrieve structured error details for a specific job."""
    manager = manager_getter()
    jc = manager._ensure_job_controller()

    try:
        job_info = jc.get_job_info(job_id=job_uuid)
    except Exception as exc:
        raise QueryError(f"Query failed for job '{job_uuid}': {exc}")

    if job_info is None:
        raise QueryError(f"Job '{job_uuid}' not found during post-query verification.")

    raw_state = job_info.state.value
    error_traceback = getattr(getattr(job_info, "remote", None), "error", None) or getattr(job_info, "error", None)

    if not error_traceback:
        return JobErrorResponse(state=raw_state, available=False)

    message = _extract_error_message(error_traceback)

    return JobErrorResponse(
        state=raw_state,
        available=True,
        message=message,
        traceback=error_traceback,
    )


def _extract_error_message(traceback_str: str) -> str:
    """Extract a short error message from a traceback string."""
    lines = traceback_str.strip().splitlines()
    for line in reversed(lines):
        stripped = line.strip()
        if stripped:
            return stripped
    return traceback_str.strip()[:200]


def get_task_summary_list(
    username: str,
    manager_getter: Callable[[], MainWorkflow],
) -> list[TaskSummary]:
    """Get a list of task summaries for the specified user."""
    task_ids = qdyndb.get_user_tasks(username)
    summaries = []

    queued_entries = qdyndb.list_queued_for_user(username)
    queued_map: dict[str, dict] = {}
    for entry in queued_entries:
        if entry["status"] in ("QUEUED", "DISPATCHING", "FAILED", "CANCELLED"):
            queued_map[entry["task_id"]] = entry

    failed_but_submitted = []
    for tid, entry in queued_map.items():
        if entry["status"] == "FAILED":
            real_job_ids = qdyndb.get_task_job_ids(tid)
            if real_job_ids:
                failed_but_submitted.append(tid)
    for tid in failed_but_submitted:
        del queued_map[tid]

    all_queued = qdyndb.list_all_queued()
    queue_positions: dict[str, int] = {
        q["task_id"]: i + 1 for i, q in enumerate(all_queued)
    }

    for task_id in task_ids:
        if task_id in queued_map:
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
    queue_positions: dict[str, int],
) -> TaskSummary:
    """Build a TaskSummary for a task still in the waiting queue."""
    import time as _time
    from datetime import datetime, timezone

    meta = qdyndb.get_task_metadata(task_id) or {}

    created_at: float = _time.time()
    try:
        dt = datetime.strptime(
            queue_entry["created_at"], "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=timezone.utc)
        created_at = dt.timestamp()
    except Exception:
        pass

    queue_status = queue_entry["status"]

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
        resume_earliest_step=None,
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
    """Get detailed status for all jobs under a task."""
    owner = qdyndb.get_task_owner(task_id)
    if owner is None:
        raise ValueError(f"Task '{task_id}' not found")

    job_ids = qdyndb.get_task_job_ids(task_id)

    queue_entry = qdyndb.get_queued_status(task_id)
    if queue_entry is not None:
        q_status = queue_entry["status"]
        if q_status in ("QUEUED", "DISPATCHING", "CANCELLED"):
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

    all_uuids: list[str] = []
    for uuid_list in job_ids.values():
        all_uuids.extend(uuid_list)

    uuid_to_job_info: dict[str, object] = {}
    if all_uuids:
        try:
            manager = manager_getter()
            jc = manager._ensure_job_controller()
            job_infos = jc.get_jobs_info_query(
                query={"uuid": {"$in": all_uuids}}
            )
            for ji in job_infos:
                existing = uuid_to_job_info.get(ji.uuid)
                if existing is None or getattr(ji, "index", 0) > getattr(existing, "index", 0):
                    uuid_to_job_info[ji.uuid] = ji
        except Exception:
            logger.warning(
                "Batch job info query failed for task %s, falling back to per-job queries",
                task_id,
            )

    jobs: list[JobStatusItem] = []
    raw_status_counts: dict[str, int] = {}
    failed_job_names: list[str] = []

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


def _get_step_order(job_ids: dict) -> list[str]:
    """Return the step ordering based on which steps exist."""
    if "fused_scf_prenamd" in job_ids:
        return STEP_ORDER_FUSED
    return STEP_ORDER_NORMAL


def _build_task_summary(
    task_id: str,
    manager_getter: Callable[[], MainWorkflow],
) -> TaskSummary | None:
    """Build a TaskSummary for a single task."""
    owner = qdyndb.get_task_owner(task_id)
    if owner is None:
        return None

    job_ids = qdyndb.get_task_job_ids(task_id)

    raw_status_counts: dict[str, int] = {}
    total_jobs = 0
    failed_job_names: list[str] = []
    step_all_completed: dict[str, bool] = {}

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
                raw_status_counts["ERROR"] = raw_status_counts.get("ERROR", 0) + 1
                all_completed_for_step = False

        step_all_completed[step_name] = all_completed_for_step

    step_order = _get_step_order(job_ids)
    steps = [s for s in step_order if s in job_ids]

    completed_steps: list[str] = []
    for s in steps:
        if step_all_completed.get(s, False):
            completed_steps.append(s)
        else:
            break

    resume_next_step: str | None = None
    resume_earliest_step: str | None = None
    if completed_steps:
        first_completed = completed_steps[0]
        first_idx = step_order.index(first_completed)
        if first_idx + 1 < len(step_order):
            resume_earliest_step = step_order[first_idx + 1]

        last_completed = completed_steps[-1]
        last_idx = step_order.index(last_completed)
        if last_idx + 1 < len(step_order):
            resume_next_step = step_order[last_idx + 1]

    created_at = _get_task_created_at_fallback(task_id)
    derived_status = derive_task_status(raw_status_counts)

    resume_eligible = (
        resume_earliest_step is not None
        and derived_status in ("COMPLETED", "FAILED")
    )

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
        resume_earliest_step=resume_earliest_step,
        resume_eligible=resume_eligible,
        pool_name=meta.get("pool_name"),
        runtime_worker=meta.get("worker"),
    )


def _get_task_created_at_fallback(task_id: str) -> float:
    """Get the creation timestamp for a task."""
    import time

    created_at = qdyndb.get_task_created_at(task_id)
    if created_at is not None:
        return created_at

    return time.time()
