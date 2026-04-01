"""
Pydantic models for frontend API responses and requests.

This module defines the data models for the frontend API layer,
implementing a dual-layer status model: raw status passthrough
plus derived status for UI consumption.
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class JobStatusItem(BaseModel):
    """Single job status information."""

    uuid: str
    name: str
    # Raw status string from jobflow-remote JobInfo.state
    state: str
    # Derived status for UI display
    derived_state: Optional[str] = None  # "RUNNING" | "COMPLETED" | "FAILED" | "PENDING" | "PAUSED" | "ERROR"
    error: Optional[str] = None
    index: int


class JobStatusDetailResponse(BaseModel):
    """Detailed status response for a single job."""

    uuid: str
    name: str
    state: str
    derived_state: Optional[str] = None  # "RUNNING" | "COMPLETED" | "FAILED" | "PENDING" | "PAUSED" | "ERROR"
    error: Optional[str] = None
    log_note: Optional[str] = None


class TaskJobsStatusResponse(BaseModel):
    """Response containing status of all jobs under a task."""

    task_id: str
    # Raw status counts, preserving all original states from jobflow-remote
    raw_status_counts: Dict[str, int]
    # Derived status for quick UI assessment
    derived_status: str  # "RUNNING" | "FAILED" | "COMPLETED" | "PENDING" | "PAUSED" | "ERROR"
    jobs: List[JobStatusItem]


class TaskSummary(BaseModel):
    """Task summary information for list display."""

    task_id: str
    owner: str
    created_at: float
    # Raw status counts preserved from jobflow-remote
    raw_status_counts: Dict[str, int]
    # Derived status for UI
    derived_status: str  # "RUNNING" | "FAILED" | "COMPLETED" | "PENDING" | "PAUSED" | "ERROR"
    total_jobs: int
    # Optional: names of failed jobs for quick identification
    failed_job_names: List[str] = Field(default_factory=list)


class TaskSummaryListResponse(BaseModel):
    """Response for task summary list endpoint."""

    total: int
    items: List[TaskSummary]


class JobErrorResponse(BaseModel):
    """Structured error information for a failed job."""

    state: str
    available: bool
    message: Optional[str] = None
    traceback: Optional[str] = None


class StopFailedItem(BaseModel):
    """Information about a job that failed to stop."""

    uuid: str
    error: str


class StopResultResponse(BaseModel):
    """Result of a stop operation, showing per-job outcomes."""

    stopped: List[str] = Field(default_factory=list)
    skipped: List[str] = Field(default_factory=list)
    failed: List[StopFailedItem] = Field(default_factory=list)


class StructureValidationRequest(BaseModel):
    """Request payload for POSCAR structure validation."""

    content: str


class StructureValidationInfo(BaseModel):
    """Parsed structure summary for frontend display."""

    num_atoms: int
    formula: str
    lattice: List[List[float]]


class StructureValidationResponse(BaseModel):
    """Response payload for POSCAR structure validation."""

    valid: bool
    error: Optional[str] = None
    structure: Optional[StructureValidationInfo] = None


# ============================================
# Job Files, Progress, and Images Models
# ============================================


class JobFileItem(BaseModel):
    """Single file entry from a job's run directory."""

    name: str
    size: int
    url: str  # Relative URL, e.g. /frontend/tasks/{id}/jobs/{uuid}/files/{name}


class JobFilesResponse(BaseModel):
    """Response listing available files in a job's run directory."""

    available: bool
    files: List[JobFileItem] = Field(default_factory=list)


class SCFBatchInfo(BaseModel):
    """Batch-level frame statistics for an SCF job."""

    completed: int = 0
    converged: int = 0
    failed: int = 0
    running: int = 0
    pending: int = 0


class SCFCurrentFrame(BaseModel):
    """Details about the currently running SCF frame."""

    name: str = ""
    global_index: int = 0
    status: str = ""  # "RUNNING"
    electronic_step_current: Optional[int] = None
    electronic_step_limit: Optional[int] = None
    scf_algorithm: Optional[str] = None
    converged: Optional[bool] = None  # None=running, True/False=done


class JobProgressResponse(BaseModel):
    """Response describing a job's progress (MD steps or SCF convergence)."""

    available: bool
    step_type: Optional[str] = None  # "nvt" / "nve" / "scf" / "other"
    current_step: int = 0
    total_steps: Optional[int] = None
    percent: Optional[float] = None
    last_temp: Optional[float] = None  # NVT/NVE only
    last_energy: Optional[float] = None
    # SCF fine-grained fields
    batch: Optional[SCFBatchInfo] = None
    current_frame: Optional[SCFCurrentFrame] = None


class JobImageItem(BaseModel):
    """Single image entry from a job's output."""

    name: str
    url: str


class JobImagesResponse(BaseModel):
    """Response listing result images for a completed job."""

    available: bool
    images: List[JobImageItem] = Field(default_factory=list)


