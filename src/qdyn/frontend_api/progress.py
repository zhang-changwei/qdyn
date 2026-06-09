"""Job progress services (MD and SCF progress tracking)."""

import logging
from pathlib import Path

from ._common import _detect_step_type, _get_task_run_dir_access
from ..main_workflow import MainWorkflow
from .run_dir_access import RunDirAccess
from .models import (
    JobProgressResponse,
    SCFBatchInfo,
    SCFCurrentFrame,
)

logger = logging.getLogger(__name__)


def _parse_nsw_from_incar(incar_path: Path) -> int | None:
    """Parse the NSW value from an INCAR file."""
    try:
        with open(incar_path, "r") as f:
            for line in f:
                stripped = line.strip().upper()
                if "NSW" in stripped:
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
    """Get the progress of a running or completed job.

    For NVT/NVE jobs, parses qdyn_md.log for MD step count and temperature.
    For SCF jobs, returns a basic available=True with step_type="scf".
    """
    jc = manager._ensure_job_controller()
    try:
        job_info = jc.get_job_info(job_id=job_uuid)
    except Exception:
        return JobProgressResponse(available=False)

    if job_info is None:
        return JobProgressResponse(available=False)

    raw_state = job_info.state.value

    if raw_state in ("WAITING", "READY", "CHECKED_OUT"):
        return JobProgressResponse(available=False)

    access = _get_task_run_dir_access(manager, task_id, job_uuid)
    if access is None:
        return JobProgressResponse(available=False)

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
    """Get SCF batch progress from log-derived status scan."""
    scf_map = access.scan_scf_status()
    if not scf_map:
        return JobProgressResponse(available=True, step_type="scf", current_step=0)

    total = len(scf_map)
    completed = 0
    running = 0
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

    Falls back to a log-based status scan when the log is absent or unreadable.
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
