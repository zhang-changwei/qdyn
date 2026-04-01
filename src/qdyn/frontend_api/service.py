"""
Service layer for frontend API.

This module provides business logic functions for the frontend API layer,
including status derivation, job info retrieval, and task summaries.
All functions that need MainWorkflow access receive it via dependency
injection (manager_getter) to avoid circular imports with app.py.
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Dict, List, Optional

from ..database import qdyndb
from ..main_workflow import MainWorkflow, QueryError
from .models import (
    JobErrorResponse,
    JobFileItem,
    JobImageItem,
    JobImagesResponse,
    JobProgressResponse,
    JobStatusItem,
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
    raw_state = manager.get_job_status(job_uuid)

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

    return TaskJobsStatusResponse(
        task_id=task_id,
        raw_status_counts=raw_status_counts,
        derived_status=derived_status,
        jobs=jobs,
    )


def _build_task_summary(
    task_id: str,
    manager_getter: Callable[[], MainWorkflow],
) -> Optional[TaskSummary]:
    """
    Build a TaskSummary for a single task.

    This is an internal helper function.

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

    # Collect status counts
    raw_status_counts: Dict[str, int] = {}
    total_jobs = 0
    failed_job_names: List[str] = []

    for step_name, uuid_list in job_ids.items():
        for idx, job_uuid in enumerate(uuid_list):
            total_jobs += 1
            try:
                manager = manager_getter()
                raw_state = manager.get_job_status(job_uuid)
                raw_status_counts[raw_state] = raw_status_counts.get(raw_state, 0) + 1

                if raw_state == "FAILED":
                    failed_job_names.append(f"{step_name}_{idx}")

            except Exception:
                # Count unknown/query errors as ERROR
                raw_status_counts["ERROR"] = raw_status_counts.get("ERROR", 0) + 1

    # Get created_at timestamp from database
    # Note: The current QdynDB schema stores created_at as a datetime string.
    # We need to query it directly since get_task_job_ids doesn't include it.
    # For now, use current time as a fallback.
    # TODO: Add a get_task_created_at method to QdynDB or extend the query.
    created_at = _get_task_created_at_fallback(task_id)

    derived_status = derive_task_status(raw_status_counts)

    return TaskSummary(
        task_id=task_id,
        owner=owner,
        created_at=created_at,
        raw_status_counts=raw_status_counts,
        derived_status=derived_status,
        total_jobs=total_jobs,
        failed_job_names=failed_job_names,
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

# Whitelist for file listing
_ALLOWED_EXTENSIONS = {".png", ".dat", ".log", ".txt"}
_ALLOWED_FILENAMES = {"OSZICAR", "OUTCAR", "CONTCAR"}
_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


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


def list_job_files(
    run_dir: Path, task_id: str, job_uuid: str
) -> List[JobFileItem]:
    """
    List whitelisted files in a job's run directory (non-recursive).

    Only includes files matching the allowed extensions or exact filenames,
    and skips files larger than 50 MB.
    """
    items: List[JobFileItem] = []

    try:
        for entry in run_dir.iterdir():
            if not entry.is_file():
                continue

            name = entry.name
            suffix = entry.suffix.lower()

            # Check whitelist
            if suffix not in _ALLOWED_EXTENSIONS and name not in _ALLOWED_FILENAMES:
                continue

            # Skip large files
            try:
                size = entry.stat().st_size
            except OSError:
                continue
            if size > _MAX_FILE_SIZE:
                continue

            url = f"/frontend/tasks/{task_id}/jobs/{job_uuid}/files/{name}"
            items.append(JobFileItem(name=name, size=size, url=url))
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
    4. Whitelist: allowed extensions or exact filenames
    5. File existence and size limit

    Returns (file_path, content_type).

    Raises:
        ValueError: If the filename is invalid, outside run_dir, or not whitelisted.
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

    # 4. Whitelist check (same constants as list_job_files)
    suffix = target.suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS and target.name not in _ALLOWED_FILENAMES:
        raise ValueError(f"File type not allowed: {filename}")

    # 5. File existence
    if not target.is_file():
        raise FileNotFoundError(f"File not found: {filename}")

    # 6. Size limit
    if target.stat().st_size > _MAX_FILE_SIZE:
        raise ValueError(f"File too large: {filename}")

    # Determine content type
    if suffix == ".png":
        content_type = "image/png"
    else:
        content_type = "text/plain; charset=utf-8"

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

