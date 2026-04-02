"""
Service layer for frontend API.

This module provides business logic functions for the frontend API layer,
including status derivation, job info retrieval, and task summaries.
All functions that need MainWorkflow access receive it via dependency
injection (manager_getter) to avoid circular imports with app.py.
"""

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..database import qdyndb
from ..main_workflow import MainWorkflow, QueryError
from .models import (
    JobErrorResponse,
    JobFileItem,
    JobImageItem,
    JobImagesResponse,
    JobInputParamsResponse,
    JobMdTimeseriesResponse,
    JobProgressResponse,
    JobStatusItem,
    MDAttemptItem,
    MDReferenceLines,
    MDSeriesData,
    MDTimeseriesStats,
    SCFBatchInfo,
    SCFCurrentFrame,
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

PAUSED_RAW_STATES = {"PAUSED", "STOPPED", "USER_STOPPED"}

PENDING_RAW_STATES = {"READY", "WAITING"}

ERROR_RAW_STATES = {"REMOTE_ERROR", "ERROR"}


def _dt_str(val: object) -> Optional[str]:
    """
    Convert a datetime-like value to an ISO string with explicit timezone.

    Jobflow-remote may return naive UTC datetimes. The frontend relies on an
    explicit UTC marker so that browsers convert them to the viewer's local
    timezone instead of treating them as already-local wall-clock time.
    """
    if val is None:
        return None

    if isinstance(val, datetime):
        dt = val if val.tzinfo is not None and val.utcoffset() is not None else val.replace(
            tzinfo=timezone.utc
        )
        return dt.isoformat().replace("+00:00", "Z")

    s = val.isoformat() if hasattr(val, "isoformat") else str(val)
    if not s:
        return s

    if " " in s and "T" not in s:
        s = s.replace(" ", "T", 1)

    if s.endswith("Z"):
        return s

    if s.endswith("+00:00"):
        return s[:-6] + "Z"

    timezone_tail = s[-6:]
    if (
        len(s) >= 6
        and timezone_tail[0] in "+-"
        and timezone_tail[1:3].isdigit()
        and timezone_tail[3] == ":"
        and timezone_tail[4:6].isdigit()
    ):
        return s

    compact_timezone_tail = s[-5:]
    if (
        len(s) >= 5
        and compact_timezone_tail[0] in "+-"
        and compact_timezone_tail[1:].isdigit()
    ):
        return s

    return f"{s}Z"


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
    4. PAUSED / STOPPED / USER_STOPPED -> "PAUSED"
    5. READY / WAITING or unknown states -> "PENDING"
    6. All COMPLETED -> "COMPLETED"

    Args:
        raw_counts: A dictionary mapping raw state strings to their counts.

    Returns:
        A derived status string: "RUNNING" | "FAILED" | "COMPLETED" | "PENDING" | "PAUSED" | "ERROR"
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

    # Priority 4: Paused states
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
        A derived status string: "RUNNING" | "COMPLETED" | "FAILED" | "PENDING" | "PAUSED" | "ERROR"
    """
    if raw_state in ERROR_RAW_STATES:
        return "ERROR"
    if raw_state == "FAILED":
        return "FAILED"
    if raw_state in RUNNING_RAW_STATES:
        return "RUNNING"
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
            job_name = f"{step_name}_{uuid_list.index(job_uuid)}"
            job_index = uuid_list.index(job_uuid)
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
    manager_getter: Optional[Callable[[], MainWorkflow]] = None,
) -> Optional[str]:
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

    Args:
        username: The username to query tasks for.
        manager_getter: A callable that returns the MainWorkflow instance.

    Returns:
        A list of TaskSummary objects for the user's tasks.
    """
    task_ids = qdyndb.get_user_tasks(username)
    summaries = []

    for task_id in task_ids:
        summary = _build_task_summary(task_id, manager_getter)
        if summary is not None:
            summaries.append(summary)

    return summaries


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
                job_item = JobStatusItem(
                    uuid=job_uuid,
                    name=f"{step_name}_{idx}",
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

    # Retrieve prev_task_id from task metadata (resume chain)
    task_meta = qdyndb.get_task_metadata(task_id)
    prev_task_id = task_meta.get("prev_task_id") if task_meta else None

    return TaskJobsStatusResponse(
        task_id=task_id,
        raw_status_counts=raw_status_counts,
        derived_status=derived_status,
        jobs=jobs,
        prev_task_id=prev_task_id,
    )


# Canonical step ordering used for resume eligibility computation
_STEP_ORDER = ["nvt", "nve", "scf", "pre_namd", "namd"]


def _build_task_summary(
    task_id: str,
    manager_getter: Callable[[], MainWorkflow],
) -> Optional[TaskSummary]:
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
    steps = [s for s in _STEP_ORDER if s in job_ids]

    # Compute completed_steps: contiguous prefix of fully-completed steps
    completed_steps: List[str] = []
    for s in steps:
        if step_all_completed.get(s, False):
            completed_steps.append(s)
        else:
            break  # stop at first incomplete step

    # Compute resume_next_step: the step right after the last completed one
    resume_next_step: Optional[str] = None
    if completed_steps:
        last_completed = completed_steps[-1]
        last_idx = _STEP_ORDER.index(last_completed)
        if last_idx + 1 < len(_STEP_ORDER):
            resume_next_step = _STEP_ORDER[last_idx + 1]

    created_at = _get_task_created_at_fallback(task_id)
    derived_status = derive_task_status(raw_status_counts)

    # Resume eligibility: must have a valid next step, and the task must
    # have finished running (COMPLETED or FAILED).
    resume_eligible = (
        resume_next_step is not None
        and derived_status in ("COMPLETED", "FAILED")
    )

    # Fetch persisted metadata (formula, num_atoms, prev_task_id)
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
        formula=meta.get("formula"),
        num_atoms=meta.get("num_atoms"),
        prev_task_id=meta.get("prev_task_id"),
        resume_next_step=resume_next_step,
        resume_eligible=resume_eligible,
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
    from datetime import datetime

    try:
        conn = qdyndb.get_db()
        row = conn.execute(
            "SELECT created_at FROM task_owners WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row:
            # SQLite stores datetime as string like "2026-03-27 12:34:56"
            # Parse and convert to timestamp
            dt = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
            return dt.timestamp()
    except Exception:
        pass

    # Fallback to current time if we can't parse
    return time.time()


# -----------------------------------------------------------------------------
# Job run directory helpers
# -----------------------------------------------------------------------------

# Blacklist: skip these files (core dumps, temporary/lock files, etc.)
_BLACKLISTED_PATTERNS = {"core", "core.*", "vasprun.xml.lock"}
_BLACKLISTED_EXTENSIONS = {".tmp", ".bak", ".swp", ".swo", ".pid", ".lock"}

# Large file warning threshold (exposed in file listing for frontend display)
_LARGE_FILE_THRESHOLD = 50 * 1024 * 1024  # 50 MB

# File category classification
_INPUT_FILENAMES = {"INCAR", "KPOINTS", "POSCAR", "POTCAR"}
_OUTPUT_FILENAMES = {
    "CONTCAR", "OUTCAR", "OSZICAR", "vasprun.xml",
    "EIGENVAL", "DOSCAR", "PROCAR", "XDATCAR",
    "CHG", "CHGCAR", "WAVECAR", "IBZKPT", "PCDAT",
    "REPORT", "ELFCAR", "LOCPOT", "AECCAR0", "AECCAR2",
}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".bmp"}


def _classify_file(name: str) -> str:
    """Classify a file into a category based on its name and extension."""
    suffix = Path(name).suffix.lower()
    stem = name

    if stem in _INPUT_FILENAMES:
        return "input"
    if stem in _OUTPUT_FILENAMES:
        return "output"
    if suffix in _IMAGE_EXTENSIONS:
        return "image"
    # Default: data (logs, .dat, .txt, and everything else)
    return "data"


def _is_blacklisted(name: str) -> bool:
    """Check if a filename should be excluded from listing."""
    suffix = Path(name).suffix.lower()
    if suffix in _BLACKLISTED_EXTENSIONS:
        return True
    # Exact match or glob-style prefix match for core dumps
    if name in _BLACKLISTED_PATTERNS:
        return True
    if name.startswith("core."):
        return True
    return False


def get_job_run_dir(
    manager: MainWorkflow, job_uuid: str
) -> Optional[Path]:
    """
    Get the run directory path for a job.

    Returns None if the job has no run_dir yet (e.g. WAITING/READY state).
    """
    jc = manager._ensure_job_controller()
    try:
        job_info = jc.get_job_info(job_id=job_uuid)
    except Exception:
        return None

    if job_info is None:
        return None

    run_dir = getattr(job_info, "run_dir", None)
    if not run_dir:
        return None

    p = Path(str(run_dir))
    if p.is_dir():
        return p
    return None


def _parse_incar_file(incar_path: Path) -> Dict[str, str]:
    """Parse an INCAR file into a key-value dictionary.

    Uses pymatgen's ``Incar`` parser for robust handling of semicolon-
    separated multi-tag lines, inline comments, and edge cases.
    Values are converted to strings for JSON serialization.
    """
    try:
        from pymatgen.io.vasp import Incar

        incar = Incar.from_file(str(incar_path))
        return {str(k): str(v) for k, v in incar.items()}
    except Exception as exc:
        logger.warning("Failed to parse INCAR at %s: %s", incar_path, exc)
        return {}


def get_job_input_params(
    manager: MainWorkflow, job_uuid: str
) -> JobInputParamsResponse:
    """Read INCAR and KPOINTS from a job's run directory.

    Returns a ``JobInputParamsResponse`` with parsed data,
    or ``available=False`` when the run directory is not ready.
    """
    run_dir = get_job_run_dir(manager, job_uuid)
    if run_dir is None:
        return JobInputParamsResponse(available=False)

    # Security: only read files directly inside run_dir
    incar_path = (run_dir / "INCAR").resolve()
    kpoints_path = (run_dir / "KPOINTS").resolve()

    # Verify paths are inside run_dir (prevent symlink escapes)
    base = run_dir.resolve()
    try:
        incar_path.relative_to(base)
        kpoints_path.relative_to(base)
    except ValueError:
        return JobInputParamsResponse(
            available=False, warning="Path traversal detected"
        )

    incar: Optional[Dict[str, str]] = None
    kpoints_text: Optional[str] = None
    warnings: list[str] = []

    # Parse INCAR
    if incar_path.is_file():
        incar = _parse_incar_file(incar_path)
    else:
        warnings.append("INCAR not found")

    # Read KPOINTS
    if kpoints_path.is_file():
        try:
            kpoints_text = kpoints_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            warnings.append(f"Failed to read KPOINTS: {exc}")
    else:
        warnings.append("KPOINTS not found")

    warning_str = "; ".join(warnings) if warnings else None

    return JobInputParamsResponse(
        available=True,
        incar=incar,
        kpoints_text=kpoints_text,
        warning=warning_str,
    )


def list_job_files(
    run_dir: Path, task_id: str, job_uuid: str
) -> List[JobFileItem]:
    """
    List files in a job's run directory (non-recursive).

    All files are listed except those matching the blacklist (core dumps,
    temporary/lock files, etc.). Files are classified into categories:
    input, output, data, or image.
    """
    items: List[JobFileItem] = []

    try:
        for entry in run_dir.iterdir():
            if not entry.is_file():
                continue

            name = entry.name

            # Check blacklist
            if _is_blacklisted(name):
                continue

            # Get file size (skip if inaccessible)
            try:
                size = entry.stat().st_size
            except OSError:
                continue

            url = f"/frontend/tasks/{task_id}/jobs/{job_uuid}/files/{name}"
            category = _classify_file(name)
            items.append(JobFileItem(name=name, size=size, url=url, category=category))
    except OSError as exc:
        logger.warning("Failed to list files in %s: %s", run_dir, exc)

    return items


def serve_job_file(
    run_dir: Path, filename: str
) -> tuple[Path, str]:
    """
    Resolve and validate a file request within a job's run directory.

    Security checks (in order):
    1. Reject path separators in filename
    2. resolve() + relative_to() path containment
    3. Single-level only (no subdirectory access)
    4. Blacklist check (reject known dangerous files)
    5. File existence

    Returns (file_path, content_type).

    Raises:
        ValueError: If the filename is invalid, outside run_dir, or blacklisted.
        FileNotFoundError: If the file does not exist.
    """
    # 1. Reject path separators in filename
    if "/" in filename or "\\" in filename:
        raise ValueError(f"Invalid filename: {filename}")

    # 2. resolve() + relative_to() for real path containment
    base = run_dir.resolve()
    target = (base / filename).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise ValueError(f"Path traversal detected: {filename}")

    # 3. Only allow root-level files (no subdirectory access)
    if target.parent != base:
        raise ValueError(f"Subdirectory access not allowed: {filename}")

    # 4. Blacklist check
    if _is_blacklisted(filename):
        raise ValueError(f"File type not allowed: {filename}")

    # 5. File existence
    if not target.is_file():
        raise FileNotFoundError(f"File not found: {filename}")

    # Determine content type
    suffix = target.suffix.lower()
    content_type_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".xml": "application/xml",
    }
    content_type = content_type_map.get(suffix, "application/octet-stream")

    return target, content_type


# -----------------------------------------------------------------------------
# Job progress
# -----------------------------------------------------------------------------


def _detect_step_type(job_name: str, run_dir: Optional[Path]) -> str:
    """Detect the step type from job name or run_dir path."""
    name_lower = job_name.lower()
    if "nvt" in name_lower:
        return "nvt"
    if "nve" in name_lower:
        return "nve"
    if "scf" in name_lower:
        return "scf"
    if run_dir:
        dir_lower = str(run_dir).lower()
        if "nvt" in dir_lower:
            return "nvt"
        if "nve" in dir_lower:
            return "nve"
        if "scf" in dir_lower:
            return "scf"
    return "other"


def _parse_nsw_from_incar(incar_path: Path) -> Optional[int]:
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


def read_file_tail(path: Path, max_bytes: int = 65536) -> str:
    """
    Read the tail of a file efficiently using binary seek.

    Seeks to the end of the file and reads the last *max_bytes* bytes,
    then decodes with error replacement.  The first (potentially
    incomplete) line is discarded so that only complete lines are
    returned.

    Args:
        path: Path to the file.
        max_bytes: Maximum number of bytes to read from the tail.

    Returns:
        A string of complete lines from the file tail.  May be empty
        if the file is empty or unreadable.
    """
    try:
        size = path.stat().st_size
        if size == 0:
            return ""
        with open(path, "rb") as f:
            read_start = max(0, size - max_bytes)
            f.seek(read_start)
            raw = f.read()
        text = raw.decode("utf-8", errors="replace")
        # If we didn't start at byte 0 the first line may be incomplete
        if read_start > 0:
            newline_pos = text.find("\n")
            if newline_pos != -1:
                text = text[newline_pos + 1 :]
        return text
    except OSError:
        return ""


def _parse_nelm_from_incar(incar_path: Path) -> Optional[int]:
    """Parse the NELM value (electronic step limit) from an INCAR file.

    Uses exact key matching to avoid false hits on NELMIN or similar keys.
    """
    import re
    nelm_pattern = re.compile(r'^\s*NELM\s*=\s*(\d+)', re.IGNORECASE)
    try:
        with open(incar_path, "r") as f:
            for line in f:
                m = nelm_pattern.match(line)
                if m:
                    return int(m.group(1))
    except OSError:
        pass
    return None


def _parse_oszicar_tail(oszicar_path: Path) -> dict:
    """
    Parse the last complete electronic step from an OSZICAR file tail.

    Uses ``read_file_tail`` to avoid reading the entire file.  Looks for
    lines matching the VASP electronic-step format::

        <ALGORITHM> : <N>  <E>  <dE>  <deps>  <rms>  <rms(c)>

    where ``<ALGORITHM>`` is typically ``CG`` or ``RMM``.

    Returns:
        A dict with keys ``electronic_step_current``, ``scf_algorithm``,
        ``last_energy``.  Values are ``None`` if parsing fails.
    """
    result = {
        "electronic_step_current": None,
        "scf_algorithm": None,
        "last_energy": None,
    }

    tail = read_file_tail(oszicar_path)
    if not tail:
        return result

    # Walk lines in reverse to find the last complete electronic step line.
    # Electronic step lines look like: "       CG       1    -0.12345 ..."
    # We match the "<algo> : <N>" pattern.
    import re

    estep_re = re.compile(
        r"^\s*(CG|RMM|DAV|PMM|Mixed)\s*:\s*(\d+)\s+"
        r"([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)"
    )

    for line in reversed(tail.splitlines()):
        m = estep_re.match(line)
        if m:
            result["scf_algorithm"] = m.group(1)
            try:
                result["electronic_step_current"] = int(m.group(2))
                result["last_energy"] = float(m.group(3))
            except ValueError:
                pass
            break

    return result


def get_job_progress(
    manager: MainWorkflow, job_uuid: str
) -> JobProgressResponse:
    """
    Get the progress of a running or completed job.

    For NVT/NVE jobs, parses OSZICAR for MD step count and temperature.
    For SCF jobs, returns a basic available=True with step_type="scf".

    Uses a single ``jc.get_job_info()`` call to retrieve state, run_dir,
    and job name, avoiding the previous 3-query overhead.
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

    # Extract run_dir from the single job_info query
    raw_run_dir = getattr(job_info, "run_dir", None)
    if not raw_run_dir:
        return JobProgressResponse(available=False)
    run_dir = Path(str(raw_run_dir))
    if not run_dir.is_dir():
        return JobProgressResponse(available=False)

    # Extract job name from the same job_info object
    job_name = getattr(job_info, "name", "") or ""

    step_type = _detect_step_type(job_name, run_dir)

    if step_type in ("nvt", "nve"):
        return _get_md_progress(run_dir, step_type)
    elif step_type == "scf":
        return _get_scf_progress(run_dir)
    else:
        return JobProgressResponse(available=True, step_type=step_type, current_step=0)


def _get_md_progress(run_dir: Path, step_type: str) -> JobProgressResponse:
    """
    Parse OSZICAR in run_dir to get MD progress.

    Uses ``read_file_tail`` to read only the last portion of the file
    instead of loading the entire OSZICAR, which can grow very large
    for long MD simulations (thousands of ionic steps).

    The current ionic step number is extracted from the last ``T=`` line.
    """
    oszicar_path = run_dir / "OSZICAR"
    incar_path = run_dir / "INCAR"

    current_step = 0
    last_temp: Optional[float] = None
    last_energy: Optional[float] = None

    if oszicar_path.is_file():
        try:
            tail = read_file_tail(oszicar_path)
            if tail:
                # Walk lines in reverse to find the last MD summary line
                for line in reversed(tail.splitlines()):
                    if "T=" in line:
                        try:
                            values = line.split()
                            current_step = int(values[0])
                            last_temp = float(values[2])
                            last_energy = float(values[8])
                        except (ValueError, IndexError):
                            continue
                        break
        except OSError as exc:
            logger.warning("Failed to read OSZICAR at %s: %s", oszicar_path, exc)

    total_steps = _parse_nsw_from_incar(incar_path)

    percent: Optional[float] = None
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


def _get_scf_progress(run_dir: Path) -> JobProgressResponse:
    """
    Get SCF batch progress driven by status files (RUNNING/ENDED/FAIL).

    For each ``scf_*`` subdirectory the presence of status files is
    checked (no file content is read — they are empty marker files).

    Additionally, for the currently-running frame the OSZICAR tail is
    parsed to extract electronic-step progress.
    """
    scf_dirs = sorted(run_dir.glob("scf_*"))
    if not scf_dirs:
        return JobProgressResponse(available=True, step_type="scf", current_step=0)

    total = 0
    completed = 0  # ENDED
    failed = 0  # FAIL
    running = 0  # RUNNING
    running_dir: Optional[Path] = None

    for d in scf_dirs:
        if not d.is_dir():
            continue
        total += 1
        if (d / "ENDED").is_file():
            completed += 1
        elif (d / "FAIL").is_file():
            failed += 1
        elif (d / "RUNNING").is_file():
            running += 1
            running_dir = d

    pending = max(0, total - completed - failed - running)
    current_step = completed  # completed frames so far
    percent = round(current_step / total * 100, 2) if total > 0 else None

    batch_info = SCFBatchInfo(
        completed=completed,
        converged=completed,  # ENDED implies validated convergence
        failed=failed,
        running=running,
        pending=pending,
    )

    # Build current_frame if a RUNNING subdirectory exists
    current_frame: Optional[SCFCurrentFrame] = None
    if running_dir is not None:
        frame_name = running_dir.name  # e.g. "scf_017"
        # Extract global index from directory name: "scf_017" -> 17
        global_index = 0
        try:
            global_index = int(frame_name.split("_", 1)[1])
        except (ValueError, IndexError):
            pass

        # Parse electronic step from OSZICAR tail
        oszicar_path = running_dir / "OSZICAR"
        estep_info = {"electronic_step_current": None, "scf_algorithm": None, "last_energy": None}
        if oszicar_path.is_file():
            estep_info = _parse_oszicar_tail(oszicar_path)

        # Read NELM from INCAR (try frame INCAR first, then parent)
        nelm: Optional[int] = None
        frame_incar = running_dir / "INCAR"
        parent_incar = run_dir / "INCAR"
        if frame_incar.is_file():
            nelm = _parse_nelm_from_incar(frame_incar)
        if nelm is None and parent_incar.is_file():
            nelm = _parse_nelm_from_incar(parent_incar)

        current_frame = SCFCurrentFrame(
            name=frame_name,
            global_index=global_index,
            status="RUNNING",
            electronic_step_current=estep_info["electronic_step_current"],
            electronic_step_limit=nelm,
            scf_algorithm=estep_info["scf_algorithm"],
            converged=None,  # still running
        )

    return JobProgressResponse(
        available=True,
        step_type="scf",
        current_step=current_step,
        total_steps=total,
        percent=percent,
        batch=batch_info,
        current_frame=current_frame,
    )


# -----------------------------------------------------------------------------
# Job images
# -----------------------------------------------------------------------------


def get_job_images(
    manager: MainWorkflow, task_id: str, job_uuid: str
) -> JobImagesResponse:
    """
    Get result images for a completed job.

    Reads the 'images' field from the job's stored output and verifies
    that each file still exists on disk.
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

    # Get run_dir to verify file existence
    run_dir = get_job_run_dir(manager, job_uuid)

    items: List[JobImageItem] = []
    for img_path in image_paths:
        target = Path(img_path)
        basename = target.name

        # Skip images in subdirectories -- the file-serving endpoint only
        # serves root-level files from run_dir, so subdirectory images
        # would produce unreachable URLs.
        if run_dir and target.parent != run_dir:
            logger.debug(
                "Skipping subdirectory image %s (not in run_dir root)", img_path,
            )
            continue

        # Verify file exists (check absolute path first, then run_dir)
        exists = False
        if Path(img_path).is_file():
            exists = True
        elif run_dir and (run_dir / basename).is_file():
            exists = True

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
    """Discover NVT retry attempt directories and resolve file paths.

    Returns
    -------
    tuple of (oszicar_path, incar_path_or_None, selected_attempt, attempts_list)
    """
    # Discover nvt_attempt_* directories
    attempt_dirs: list[Path] = sorted(
        run_dir.glob("nvt_attempt_*"),
        key=lambda p: int(p.name.split("_")[-1]) if p.name.split("_")[-1].isdigit() else 0,
    )

    # Build attempt list
    attempts: list[MDAttemptItem] = []
    max_archived = 0
    for d in attempt_dirs:
        if not d.is_dir():
            continue
        try:
            num = int(d.name.split("_")[-1])
        except ValueError:
            continue
        if (d / "OSZICAR").is_file():
            attempts.append(MDAttemptItem(
                attempt=num,
                label=f"Attempt {num}",
                is_current=False,
                archived=True,
            ))
            max_archived = max(max_archived, num)

    # The root-directory OSZICAR is the "current / latest" attempt
    current_num = max_archived + 1
    root_oszicar = run_dir / "OSZICAR"
    if root_oszicar.is_file():
        attempts.append(MDAttemptItem(
            attempt=current_num,
            label=f"Attempt {current_num} (latest)" if attempts else f"Attempt {current_num}",
            is_current=True,
            archived=False,
        ))

    # NVE: no retry concept — one single attempt
    if step_type == "nve":
        if root_oszicar.is_file():
            incar_path = (run_dir / "INCAR") if (run_dir / "INCAR").is_file() else None
            return root_oszicar, incar_path, 1, [
                MDAttemptItem(attempt=1, label="Attempt 1", is_current=True, archived=False),
            ]
        raise FileNotFoundError("OSZICAR not found in run_dir for NVE job.")

    # Determine which attempt to serve
    if attempt is None:
        # Default: latest (root directory)
        selected = current_num
    else:
        selected = attempt

    # Resolve paths for the selected attempt
    if selected == current_num and root_oszicar.is_file():
        oszicar_path = root_oszicar
        incar_path = (run_dir / "INCAR") if (run_dir / "INCAR").is_file() else None
    else:
        attempt_dir = run_dir / f"nvt_attempt_{selected}"
        oszicar_path = attempt_dir / "OSZICAR"
        if not oszicar_path.is_file():
            raise FileNotFoundError(
                f"OSZICAR not found for attempt {selected} "
                f"(looked in {attempt_dir})."
            )
        incar_path = (attempt_dir / "INCAR") if (attempt_dir / "INCAR").is_file() else None

    return oszicar_path, incar_path, selected, attempts


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
    job_uuid: str,
    attempt: int | None,
    max_points: int,
) -> JobMdTimeseriesResponse:
    """Build the full MD timeseries response for a job.

    This is the main entry point called by the router.
    """
    from ..output_postprocess import parse_md_data_from_oszicar

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

    run_dir = Path(str(raw_run_dir))
    if not run_dir.is_dir():
        return JobMdTimeseriesResponse(available=False, warning="Job run directory does not exist.")

    step_type = _detect_step_type(job_name, run_dir)
    if step_type not in ("nvt", "nve"):
        return JobMdTimeseriesResponse(
            available=False,
            step_type=step_type,
            warning=f"MD timeseries not applicable for step_type '{step_type}'.",
        )

    # --- Resolve attempt files ---
    try:
        oszicar_path, incar_path, selected_attempt, attempts = _resolve_md_attempt_files(
            run_dir, step_type, attempt,
        )
    except FileNotFoundError as exc:
        return JobMdTimeseriesResponse(
            available=False,
            step_type=step_type,
            state=raw_state,
            warning=str(exc),
        )

    # --- Parse OSZICAR ---
    try:
        raw_data = parse_md_data_from_oszicar(oszicar_path, incar_path)
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

    # --- Build time_fs from POTIM ---
    potim = None
    if incar_path is not None:
        potim = _parse_incar_numeric_value(incar_path, "POTIM")
    if potim is not None and potim > 0:
        time_fs = [s * potim for s in raw_data['steps']]
    else:
        # Fallback: use step number directly
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

    # --- NSW for total_steps ---
    total_steps: int | None = None
    if incar_path is not None:
        nsw_val = _parse_incar_numeric_value(incar_path, "NSW")
        if nsw_val is not None:
            total_steps = int(nsw_val)

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
