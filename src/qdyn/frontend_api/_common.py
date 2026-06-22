"""Common helpers shared across frontend API service modules."""

import logging
from datetime import datetime, timezone

from ..main_workflow import MainWorkflow
from .run_dir_access import RunDirAccess

logger = logging.getLogger(__name__)


def _get_task_run_dir_access(
    manager: MainWorkflow,
    task_id: str,
    job_uuid: str,
) -> RunDirAccess | None:
    """Build run-dir access using the task's owning pool."""
    return manager.get_task_pool(task_id).build_run_dir_access(job_uuid)


def _dt_str(val: object) -> str | None:
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


def _detect_step_type(job_name: str, run_dir_path: str | None = None) -> str:
    """Detect the step type from job name or run_dir path string."""
    name_lower = job_name.lower()
    # Fused detection first (avoids "scf"/"namd" substring false matches)
    if "fused" in name_lower:
        return "fused_scf_prenamd"
    if "cat_canac" in name_lower:
        return "fused_cat"
    if "pre_namd" in name_lower:
        return "pre_namd"
    if "namd" in name_lower:
        return "namd"
    if "nvt" in name_lower:
        return "nvt"
    if "nve" in name_lower:
        return "nve"
    if "scf" in name_lower:
        return "scf"
    if run_dir_path:
        dir_lower = run_dir_path.lower()
        if "fused" in dir_lower:
            return "fused_scf_prenamd"
        if "cat_canac" in dir_lower:
            return "fused_cat"
        if "pre_namd" in dir_lower:
            return "pre_namd"
        if "namd" in dir_lower:
            return "namd"
        if "nvt" in dir_lower:
            return "nvt"
        if "nve" in dir_lower:
            return "nve"
        if "scf" in dir_lower:
            return "scf"
    return "other"
