"""File listing, serving, download, and image retrieval services."""

import io
import logging
import zipfile
from pathlib import Path
from typing import Dict, List, Union

from ..main_workflow import MainWorkflow
from ._common import _get_task_run_dir_access
from .run_dir_access import (
    FileInfo,
    LocalRunDirAccess,
    RunDirAccess,
)
from .models import (
    JobFileItem,
    JobImageItem,
    JobImagesResponse,
    SubdirInfo,
    ZipDownloadFileItem,
)

logger = logging.getLogger(__name__)


# Blacklist: skip these files (core dumps, temporary/lock files, etc.)
_BLACKLISTED_PATTERNS = {"core", "core.*", "vasprun.xml.lock"}
_BLACKLISTED_EXTENSIONS = {".tmp", ".bak", ".swp", ".swo", ".pid", ".lock"}

# Allowed subdirectory prefixes for file browsing (security whitelist).
_ALLOWED_SUBDIR_PREFIXES = ("scf_", "nvt_attempt_")

# Large file warning threshold (exposed in file listing for frontend display)
_LARGE_FILE_THRESHOLD = 50 * 1024 * 1024  # 50 MB
_ZIP_MAX_TOTAL_SIZE = 1024 * 1024 * 1024  # 1 GB

# File category classification
_INPUT_FILENAMES = {
    "INCAR", "KPOINTS", "POSCAR", "POTCAR",
    "nequip_in.vasp", "mace_in.vasp",
}
_OUTPUT_FILENAMES = {
    "CONTCAR", "OUTCAR", "OSZICAR", "vasprun.xml",
    "EIGENVAL", "DOSCAR", "PROCAR", "XDATCAR",
    "CHG", "CHGCAR", "WAVECAR", "IBZKPT", "PCDAT",
    "REPORT", "ELFCAR", "LOCPOT", "AECCAR0", "AECCAR2",
    "nequip_out.vasp", "mace_out.vasp", "qdyn.extxyz",
}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".bmp"}
_LOG_SUFFIXES = {".log"}


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
    if suffix in _LOG_SUFFIXES:
        return "output"
    return "data"


def _is_blacklisted(name: str) -> bool:
    """Check if a filename should be excluded from listing."""
    suffix = Path(name).suffix.lower()
    if suffix in _BLACKLISTED_EXTENSIONS:
        return True
    if name in _BLACKLISTED_PATTERNS:
        return True
    if name.startswith("core."):
        return True
    return False


def _guess_content_type(filename: str) -> str:
    """Guess MIME content type from filename extension."""
    suffix = Path(filename).suffix.lower()
    content_type_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".xml": "application/xml",
    }
    return content_type_map.get(suffix, "application/octet-stream")


def _is_allowed_subdir(subdir: str) -> bool:
    """Check if a subdirectory name matches an allowed prefix."""
    return any(subdir.startswith(p) for p in _ALLOWED_SUBDIR_PREFIXES)


def _detect_subdir_status(access: RunDirAccess, subdir: str) -> str:
    """Detect the status of a subdirectory from marker files.

    Note: For scf_* subdirectories, prefer ``scan_scf_status()`` which
    checks all subdirs in a single pass.  This function is kept as a
    fallback for non-scf subdirectories (e.g. nvt_attempt_*).
    """
    try:
        has_ended = access.subdir_file_exists(subdir, "ENDED")
        has_outcar = access.subdir_file_exists(subdir, "OUTCAR")

        if has_ended:
            return "completed"
        if has_outcar:
            return "running"
        has_poscar = access.subdir_file_exists(subdir, "POSCAR")
        if has_poscar:
            return "pending"
        return "unknown"
    except Exception:
        return "unknown"


# Map from scan_scf_status marker names to SubdirInfo display status
_SCF_STATUS_MAP = {
    "ENDED": "completed",
    "FAIL": "failed",
    "RUNNING": "running",
    "PENDING": "pending",
}


def list_job_files(
    access: RunDirAccess, task_id: str, job_uuid: str
) -> tuple[List[JobFileItem], List[SubdirInfo]]:
    """List files in a job's run directory (non-recursive) plus subdirectory
    metadata.

    Returns:
        A tuple of (root_files, subdirs).
    """
    items: List[JobFileItem] = []

    try:
        for fi in access.list_root_files():
            name = fi.name

            if _is_blacklisted(name):
                continue

            url = f"/frontend/tasks/{task_id}/jobs/{job_uuid}/files/{name}"
            category = _classify_file(name)
            items.append(
                JobFileItem(name=name, size=fi.size, url=url, category=category)
            )
    except Exception as exc:
        logger.warning(
            "Failed to list files in %s: %s", access.run_dir_path, exc
        )

    subdirs = list_job_subdirs(access, task_id, job_uuid)

    return items, subdirs


def serve_job_file(
    access: RunDirAccess, filename: str
) -> tuple[Union[Path, bytes], str]:
    """Resolve and validate a file request within a job's run directory.

    Raises:
        ValueError: If the filename is invalid or blacklisted.
        FileNotFoundError: If the file does not exist.
    """
    if "/" in filename or "\\" in filename or ".." in filename:
        raise ValueError(f"Invalid filename: {filename}")

    if _is_blacklisted(filename):
        raise ValueError(f"File type not allowed: {filename}")

    if not access.root_file_exists(filename):
        raise FileNotFoundError(f"File not found: {filename}")

    content_type = _guess_content_type(filename)

    if isinstance(access, LocalRunDirAccess):
        target = (Path(access.run_dir_path) / filename).resolve()
        base = Path(access.run_dir_path).resolve()
        try:
            target.relative_to(base)
        except ValueError:
            raise ValueError(f"Path traversal detected: {filename}")
        return target, content_type

    data = access.download_root_file(filename)
    return data, content_type


def list_job_subdirs(
    access: RunDirAccess, task_id: str, job_uuid: str
) -> List[SubdirInfo]:
    """List whitelisted subdirectories with metadata (name, file count, status)."""
    items: List[SubdirInfo] = []

    # --- Fast path: batch-scan scf_* subdirs ---
    try:
        scf_map = access.scan_scf_status()
        for subdir_name in sorted(scf_map):
            info = scf_map[subdir_name]
            status = _SCF_STATUS_MAP.get(info.status, "unknown")
            items.append(
                SubdirInfo(
                    name=subdir_name,
                    file_count=info.file_count,
                    status=status,
                )
            )
    except Exception as exc:
        logger.warning(
            "scan_scf_status failed for %s: %s", access.run_dir_path, exc
        )

    # --- Slow path: other allowed prefixes (nvt_attempt_*, etc.) ---
    non_scf_prefixes = [p for p in _ALLOWED_SUBDIR_PREFIXES if p != "scf_"]
    if non_scf_prefixes:
        try:
            other_subdirs: List[str] = []
            for prefix in non_scf_prefixes:
                other_subdirs.extend(access.list_subdirs(prefix))
            seen: set[str] = set()
            unique_others: List[str] = []
            for d in other_subdirs:
                if d not in seen:
                    seen.add(d)
                    unique_others.append(d)
            unique_others.sort()

            for subdir_name in unique_others:
                try:
                    files = access.list_subdir_files(subdir_name)
                    file_count = len(files)
                except Exception:
                    file_count = 0

                status = _detect_subdir_status(access, subdir_name)
                items.append(
                    SubdirInfo(
                        name=subdir_name,
                        file_count=file_count,
                        status=status,
                    )
                )
        except Exception as exc:
            logger.warning(
                "Failed to list non-scf subdirs in %s: %s",
                access.run_dir_path,
                exc,
            )

    return items


def list_subdir_files(
    access: RunDirAccess, task_id: str, job_uuid: str, subdir: str
) -> List[JobFileItem]:
    """List files inside a specific subdirectory of a job's run directory.

    Raises:
        ValueError: If the subdirectory is not in the allowed list.
    """
    if not _is_allowed_subdir(subdir):
        raise ValueError(
            f"Subdirectory not allowed: {subdir!r}. "
            f"Must start with one of: {_ALLOWED_SUBDIR_PREFIXES}"
        )

    items: List[JobFileItem] = []
    try:
        for fi in access.list_subdir_files(subdir):
            name = fi.name
            if _is_blacklisted(name):
                continue
            url = (
                f"/frontend/tasks/{task_id}/jobs/{job_uuid}"
                f"/files/{subdir}/{name}"
            )
            category = _classify_file(name)
            items.append(
                JobFileItem(
                    name=name, size=fi.size, url=url, category=category
                )
            )
    except Exception as exc:
        logger.warning(
            "Failed to list files in %s/%s: %s",
            access.run_dir_path, subdir, exc,
        )

    return items


def serve_subdir_file(
    access: RunDirAccess, subdir: str, filename: str
) -> tuple[Union[Path, bytes], str]:
    """Resolve and validate a file request within a job subdirectory.

    Raises:
        ValueError: If the subdir/filename is invalid or blacklisted.
        FileNotFoundError: If the file does not exist.
    """
    if not _is_allowed_subdir(subdir):
        raise ValueError(
            f"Subdirectory not allowed: {subdir!r}. "
            f"Must start with one of: {_ALLOWED_SUBDIR_PREFIXES}"
        )

    if "/" in filename or "\\" in filename or ".." in filename:
        raise ValueError(f"Invalid filename: {filename}")

    if _is_blacklisted(filename):
        raise ValueError(f"File type not allowed: {filename}")

    if not access.subdir_file_exists(subdir, filename):
        raise FileNotFoundError(f"File not found: {subdir}/{filename}")

    content_type = _guess_content_type(filename)

    if isinstance(access, LocalRunDirAccess):
        target = (Path(access.run_dir_path) / subdir / filename).resolve()
        base = Path(access.run_dir_path).resolve()
        try:
            target.relative_to(base)
        except ValueError:
            raise ValueError(f"Path traversal detected: {subdir}/{filename}")
        return target, content_type

    data = access.download_subdir_file(subdir, filename)
    return data, content_type


def build_download_zip(
    task_id: str,
    files: list[ZipDownloadFileItem],
    manager: MainWorkflow,
) -> bytes:
    """Build a zip archive containing selected job files.

    Raises:
        ValueError: If a filename or subdirectory is invalid or blacklisted.
        FileNotFoundError: If a run directory or file does not exist.
        OverflowError: If total uncompressed size exceeds the limit.
    """
    buf = io.BytesIO()
    total_size = 0
    pool = manager.get_task_pool(task_id)

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in files:
            filename = item.filename
            if not filename or "/" in filename or "\\" in filename or ".." in filename:
                raise ValueError(f"Invalid filename: {filename}")
            if _is_blacklisted(filename):
                raise ValueError(f"File type not allowed: {filename}")

            access = pool.build_run_dir_access(item.job_uuid)
            if access is None:
                raise FileNotFoundError(
                    f"Run directory not available for job {item.job_uuid}"
                )

            short_uuid = item.job_uuid[:8]
            if item.subdir:
                subdir = item.subdir
                if "/" in subdir or "\\" in subdir or ".." in subdir:
                    raise ValueError(f"Invalid subdir: {subdir}")
                if not _is_allowed_subdir(subdir):
                    raise ValueError(f"Subdirectory not allowed: {subdir}")
                if not access.subdir_file_exists(subdir, filename):
                    raise FileNotFoundError(
                        f"File not found: {subdir}/{filename}"
                    )
                data = access.download_subdir_file(subdir, filename)
                zip_path = f"{short_uuid}/{subdir}/{filename}"
            else:
                if not access.root_file_exists(filename):
                    raise FileNotFoundError(f"File not found: {filename}")
                data = access.download_root_file(filename)
                zip_path = f"{short_uuid}/{filename}"

            total_size += len(data)
            if total_size > _ZIP_MAX_TOTAL_SIZE:
                limit_mb = _ZIP_MAX_TOTAL_SIZE // (1024 * 1024)
                raise OverflowError(
                    f"Total download size exceeds {limit_mb} MB limit"
                )

            zf.writestr(zip_path, data)

    return buf.getvalue()


def get_job_images(
    manager: MainWorkflow, task_id: str, job_uuid: str
) -> JobImagesResponse:
    """Get result images for a completed job."""
    try:
        raw_state = manager.get_job_status(job_uuid)
    except Exception:
        return JobImagesResponse(available=False)

    if raw_state != "COMPLETED":
        return JobImagesResponse(available=False)

    try:
        output = manager.get_job_output(job_uuid)
    except Exception:
        return JobImagesResponse(available=False)

    if output is None:
        return JobImagesResponse(available=True)

    image_paths = output.get("images") or []
    if not image_paths:
        return JobImagesResponse(available=True)

    access = _get_task_run_dir_access(manager, task_id, job_uuid)

    items: List[JobImageItem] = []
    for img_path in image_paths:
        basename = Path(img_path).name

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
