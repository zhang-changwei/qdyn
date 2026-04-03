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
    derived_state: Optional[str] = None  # "RUNNING" | "COMPLETED" | "FAILED" | "PENDING" | "PAUSED" | "STOPPED" | "ERROR"
    error: Optional[str] = None
    index: int
    # Timestamps from jobflow-remote JobInfo (ISO format strings)
    created_on: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None


class JobStatusDetailResponse(BaseModel):
    """Detailed status response for a single job."""

    uuid: str
    name: str
    state: str
    derived_state: Optional[str] = None  # "RUNNING" | "COMPLETED" | "FAILED" | "PENDING" | "PAUSED" | "STOPPED" | "ERROR"
    error: Optional[str] = None
    log_note: Optional[str] = None


class TaskJobsStatusResponse(BaseModel):
    """Response containing status of all jobs under a task."""

    task_id: str
    # Raw status counts, preserving all original states from jobflow-remote
    raw_status_counts: Dict[str, int]
    # Derived status for quick UI assessment
    derived_status: str  # "RUNNING" | "FAILED" | "COMPLETED" | "PENDING" | "PAUSED" | "STOPPED" | "ERROR"
    jobs: List[JobStatusItem]
    # Resume chain: id of the predecessor task (if this is a resume task)
    prev_task_id: Optional[str] = None


class TaskSummary(BaseModel):
    """Task summary information for list display and resume eligibility."""

    task_id: str
    owner: str
    created_at: float
    # Raw status counts preserved from jobflow-remote
    raw_status_counts: Dict[str, int]
    # Derived status for UI
    derived_status: str  # "RUNNING" | "FAILED" | "COMPLETED" | "PENDING" | "PAUSED" | "STOPPED" | "ERROR"
    total_jobs: int
    # Optional: names of failed jobs for quick identification
    failed_job_names: List[str] = Field(default_factory=list)
    # Steps included in this task (ordered by phase)
    steps: List[str] = Field(default_factory=list)
    # Steps that have fully completed (contiguous prefix only)
    completed_steps: List[str] = Field(default_factory=list)
    # Structure metadata (persisted at submit time)
    formula: Optional[str] = None
    num_atoms: Optional[int] = None
    # Resume chain: id of the predecessor task (if this is a resume task)
    prev_task_id: Optional[str] = None
    # The next step that can be resumed from
    resume_next_step: Optional[str] = None
    # Whether this task is eligible to be resumed
    resume_eligible: bool = False


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


class ContinueResultResponse(BaseModel):
    """Result of a continue/resume operation, showing per-job outcomes."""

    continued: List[str] = Field(default_factory=list)
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
    category: str  # One of: input, output, data, image


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
    failed_frames: List[str] = Field(default_factory=list)


class JobImageItem(BaseModel):
    """Single image entry from a job's output."""

    name: str
    url: str


class JobImagesResponse(BaseModel):
    """Response listing result images for a completed job."""

    available: bool
    images: List[JobImageItem] = Field(default_factory=list)


# ============================================
# MD Timeseries Models
# ============================================


class JobInputParamsResponse(BaseModel):
    """Response containing parsed INCAR and KPOINTS data for a job."""

    available: bool
    incar: Optional[Dict[str, str]] = None
    kpoints_text: Optional[str] = None
    warning: Optional[str] = None


class MDAttemptItem(BaseModel):
    """Metadata for a single NVT retry attempt."""

    attempt: int
    label: str
    is_current: bool
    archived: bool


class MDSeriesData(BaseModel):
    """Time-series arrays for an MD trajectory."""

    steps: List[int]
    time_fs: List[float]
    temperatures: List[float]
    total_energies: List[float]
    potential_energies: List[float]
    kinetic_energies: List[float]
    converged: List[bool]


class MDReferenceLines(BaseModel):
    """Reference lines and annotation values for the chart."""

    potim_fs: Optional[float] = None
    tebeg: Optional[float] = None
    teend: Optional[float] = None
    target_temperature: Optional[float] = None
    temperature_tolerance_low: Optional[float] = None
    temperature_tolerance_high: Optional[float] = None
    mean_total_energy: Optional[float] = None
    initial_total_energy: Optional[float] = None
    energy_drift_slope_ev_per_step: Optional[float] = None


class MDTimeseriesStats(BaseModel):
    """Summary statistics for the returned timeseries data."""

    current_step: int
    total_steps: Optional[int] = None
    original_points: int
    returned_points: int
    sampled: bool


class JobMdTimeseriesResponse(BaseModel):
    """Response for the MD timeseries endpoint."""

    available: bool
    step_type: Optional[str] = None
    state: Optional[str] = None
    selected_attempt: int = 1
    attempts: List[MDAttemptItem] = Field(default_factory=list)
    series: Optional[MDSeriesData] = None
    references: Optional[MDReferenceLines] = None
    stats: Optional[MDTimeseriesStats] = None
    warning: Optional[str] = None
