"""Pydantic response models for the admin API."""

from pydantic import BaseModel

from ..frontend_api.models import TaskSummary


class AdminStatsResponse(BaseModel):
    """Dashboard statistics for the admin panel."""

    total_users: int
    total_tasks: int
    running_tasks: int  # tasks with at least one non-terminal job
    queued_tasks: int  # queued_submissions in QUEUED status
    storage_bytes: int | None  # work_dir_base directory tree size, None=computing
    traj_storage_bytes: int | None  # user_data/trajs directory size
    traj_file_count: int


class AdminUserItem(BaseModel):
    """Single user entry for the admin user list."""

    username: str
    is_admin: bool
    created_at: float | None  # Unix timestamp (UTC), same as TaskSummary
    task_count: int


class AdminTaskListResponse(BaseModel):
    """Admin task list reusing the frontend TaskSummary model."""

    total: int
    items: list[TaskSummary]


class AdminWorkerItem(BaseModel):
    """Single worker entry for the admin worker list."""

    name: str
    status: str  # "idle" | "busy"
    current_user: str | None  # via MongoDB job.metadata.qdyn_user
    active_jobs: int


# ---------------------------------------------------------------------------
# File browser models
# ---------------------------------------------------------------------------


class FileSummaryItem(BaseModel):
    """A single file entry inside a job directory."""

    name: str
    size: int


class AdminFileEntry(BaseModel):
    """A job directory entry in work_dir_base.

    ``file_summary`` is optional in stage 1+: the list endpoint no longer
    returns per-file details.  Use ``GET /api/admin/files/summary?path=...``
    to lazily fetch the file summary for an expanded row.

    ``file_count`` and ``file_summary_ready`` are populated from the
    FileIndexCache snapshot when available.
    """

    path: str
    abs_path: str
    size_bytes: int | None
    job_uuid: str
    task_id: str | None
    owner: str | None
    orphan: bool
    file_count: int | None = None
    file_summary_ready: bool = False
    file_summary: list[FileSummaryItem] | None = None


class FileSearchResultItem(BaseModel):
    """A single file matching a filename search query."""

    leaf_path: str
    file_name: str
    basename: str
    size: int


class FileSearchResponse(BaseModel):
    """Response for GET /api/admin/files/search."""

    query: str
    results: list[FileSearchResultItem]


class FileTypeStat(BaseModel):
    """Aggregated file statistics for a single basename."""

    name: str
    totalSize: int
    count: int


class FileStatsResponse(BaseModel):
    """Response for GET /api/admin/files/stats."""

    stats: list[FileTypeStat]


class FileLeafSummaryResponse(BaseModel):
    """Response for GET /api/admin/files/summary."""

    path: str
    file_summary: list[FileSummaryItem] | None
    index_status: str


class AdminFilesResponse(BaseModel):
    """Response for GET /api/admin/files."""

    work_dir_base: str
    total_entries: int
    orphan_count: int
    entries: list[AdminFileEntry]
    index_status: str


class FileDeleteTarget(BaseModel):
    """A single target for bulk file/directory deletion."""

    abs_path: str
    task_id: str | None = None


class FileDeleteRequest(BaseModel):
    """Request body for POST /api/admin/files/delete."""

    targets: list[FileDeleteTarget]
    delete_associated_tasks: bool = False


class FileDeleteFailedItem(BaseModel):
    """A single item that failed to delete."""

    path: str
    error: str


class FileDeleteResponse(BaseModel):
    """Response for POST /api/admin/files/delete."""

    deleted: int
    failed: list[FileDeleteFailedItem]


class FileNameDeleteRequest(BaseModel):
    """Request body for POST /api/admin/files/delete-by-name."""

    filename: str
    job_dirs: list[str]


# ---------------------------------------------------------------------------
# Trajectory management models
# ---------------------------------------------------------------------------


class TrajFileItem(BaseModel):
    """A single trajectory file entry."""

    hash: str
    size_bytes: int
    created_at: str
    format: str | None = None
    formula: str | None = None
    num_atoms: int | None = None
    num_frames: int | None = None
    ref_count: int = 0


class TrajListResponse(BaseModel):
    """Response for GET /api/admin/trajectories."""

    total: int
    total_bytes: int
    items: list[TrajFileItem]


# ---------------------------------------------------------------------------
# Audit log models
# ---------------------------------------------------------------------------


class AuditLogItem(BaseModel):
    """A single audit log entry."""

    id: int
    timestamp: float | None
    timestamp_raw: str | None = None
    username: str
    action: str
    target: str | None = None
    detail: str | None = None


class AuditLogResponse(BaseModel):
    """Response for GET /api/admin/audit-logs."""

    total: int
    items: list[AuditLogItem]


# ---------------------------------------------------------------------------
# Log viewer models
# ---------------------------------------------------------------------------


class LogViewResponse(BaseModel):
    """Response for GET /api/admin/logs."""

    log_name: str
    lines: list[str]
    total_lines: int
    file_size: int
