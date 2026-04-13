"""
Pydantic models for frontend API responses and requests.

This module defines the data models for the frontend API layer,
implementing a dual-layer status model: raw status passthrough
plus derived status for UI consumption.
"""

from typing import Dict, List, Literal

from pydantic import BaseModel, Field


class JobStatusItem(BaseModel):
    """Single job status information."""

    uuid: str
    name: str
    # Raw status string from jobflow-remote JobInfo.state
    state: str
    # Derived status for UI display
    derived_state: str | None = None  # "RUNNING" | "COMPLETED" | "FAILED" | "PENDING" | "PAUSED" | "STOPPED" | "ERROR"
    error: str | None = None
    index: int
    # Timestamps from jobflow-remote JobInfo (ISO format strings)
    created_on: str | None = None
    start_time: str | None = None
    end_time: str | None = None


class JobStatusDetailResponse(BaseModel):
    """Detailed status response for a single job."""

    uuid: str
    name: str
    state: str
    derived_state: str | None = None  # "RUNNING" | "COMPLETED" | "FAILED" | "PENDING" | "PAUSED" | "STOPPED" | "ERROR"
    error: str | None = None
    log_note: str | None = None


class TaskJobsStatusResponse(BaseModel):
    """Response containing status of all jobs under a task."""

    task_id: str
    # Raw status counts, preserving all original states from jobflow-remote
    raw_status_counts: Dict[str, int]
    # Derived status for quick UI assessment
    derived_status: str  # "RUNNING" | "FAILED" | "COMPLETED" | "PENDING" | "PAUSED" | "STOPPED" | "ERROR"
    jobs: List[JobStatusItem]
    # Resume chain: id of the predecessor task (if this is a resume task)
    prev_task_id: str | None = None
    # Custom task display name (user-provided or None)
    task_name: str | None = None
    # Chemical formula (persisted at submit time)
    formula: str | None = None


class TaskSummary(BaseModel):
    """Task summary information for list display and resume eligibility."""

    task_id: str
    owner: str
    created_at: float
    # Raw status counts preserved from jobflow-remote
    raw_status_counts: Dict[str, int]
    # Derived status for UI
    derived_status: str  # "RUNNING" | "FAILED" | "COMPLETED" | "PENDING" | "PAUSED" | "STOPPED" | "ERROR" | "QUEUED" | "DISPATCHING"
    total_jobs: int
    # Optional: names of failed jobs for quick identification
    failed_job_names: List[str] = Field(default_factory=list)
    # Steps included in this task (ordered by phase)
    steps: List[str] = Field(default_factory=list)
    # Steps that have fully completed (contiguous prefix only)
    completed_steps: List[str] = Field(default_factory=list)
    # Custom task display name (user-provided or None)
    task_name: str | None = None
    # Structure metadata (persisted at submit time)
    formula: str | None = None
    num_atoms: int | None = None
    # Resume chain: id of the predecessor task (if this is a resume task)
    prev_task_id: str | None = None
    # Worker used for this task (e.g. "local_slurm", "remote_djs")
    worker: str | None = None
    # The next step that can be resumed from
    resume_next_step: str | None = None
    # Whether this task is eligible to be resumed
    resume_eligible: bool = False
    # Pool-based queue fields (populated for tasks in the waiting queue)
    queue_status: str | None = None  # "QUEUED" | "DISPATCHING" | None
    queue_position: int | None = None  # 1-based position in queue
    # Logical pool name (e.g. "local_slurm")
    pool_name: str | None = None
    # Runtime worker name (e.g. "local_slurm_007")
    runtime_worker: str | None = None


class TaskSummaryListResponse(BaseModel):
    """Response for task summary list endpoint."""

    total: int
    items: List[TaskSummary]


class JobErrorResponse(BaseModel):
    """Structured error information for a failed job."""

    state: str
    available: bool
    message: str | None = None
    traceback: str | None = None


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


class StructurePreviewPayload(BaseModel):
    """Format-agnostic structure data for 3D rendering.

    Decoupled from file format. Backend parses via ASE -> outputs this.
    Frontend renderer consumes only this model.

    Invariants:
    - len(species) == len(cart_coords) == len(constraint_mask) (if not None)
    - cart_coords in Angstrom, Cartesian
    - lattice: 3x3 row vectors, Angstrom
    - pbc: [a, b, c] axis order
    """

    species: List[str]
    cart_coords: List[List[float]]
    lattice: List[List[float]]
    pbc: List[bool] = Field(default=[True, True, True])
    constraint_mask: List[bool] | None = None  # true = constrained (source-agnostic)


class StructureValidationResponse(BaseModel):
    """Response payload for POSCAR structure validation."""

    valid: bool
    error: str | None = None
    structure: StructureValidationInfo | None = None
    preview: StructurePreviewPayload | None = None


class ComputeConstraintMaskRequest(BaseModel):
    """Request payload for computing per-atom constraint mask from layer parameters."""

    stru_content: str
    stru_format: str = "vasp"
    constraint_layers: str
    layer_direction: Literal[
        '000', '001', '010', '011', '100', '101', '110', '111'
    ]
    total_layers: int = Field(ge=1)


class ComputeConstraintMaskResponse(BaseModel):
    """Response payload for constraint mask computation.

    source indicates how the mask was determined:
    - "file": structure file already contained ASE constraints (FixAtoms etc.)
    - "layers": mask was computed from the layer parameters
    """

    constraint_mask: List[bool]
    source: Literal["file", "layers"]
    warning: str | None = None


# ============================================
# Job Files, Progress, and Images Models
# ============================================


class JobFileItem(BaseModel):
    """Single file entry from a job's run directory."""

    name: str
    size: int
    url: str  # Relative URL, e.g. /frontend/tasks/{id}/jobs/{uuid}/files/{name}
    category: str  # One of: input, output, data, image


class SubdirInfo(BaseModel):
    """Metadata for a subdirectory in a job's run directory.

    Returned as part of the files listing so the frontend can display
    collapsible subdirectory groups without loading all file contents
    up front (lazy loading).
    """

    name: str
    file_count: int
    # Status derived from marker files: "completed", "failed", "running", "unknown"
    status: str = "unknown"


class JobFilesResponse(BaseModel):
    """Response listing available files in a job's run directory."""

    available: bool
    files: List[JobFileItem] = Field(default_factory=list)
    subdirs: List[SubdirInfo] = Field(default_factory=list)


class SubdirFilesResponse(BaseModel):
    """Response listing files inside a specific subdirectory."""

    available: bool
    subdir: str
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
    electronic_step_current: int | None = None
    electronic_step_limit: int | None = None
    scf_algorithm: str | None = None
    converged: bool | None = None  # None=running, True/False=done


class JobProgressResponse(BaseModel):
    """Response describing a job's progress (MD steps or SCF convergence)."""

    available: bool
    step_type: str | None = None  # "nvt" / "nve" / "scf" / "other"
    current_step: int = 0
    total_steps: int | None = None
    percent: float | None = None
    last_temp: float | None = None  # NVT/NVE only
    last_energy: float | None = None
    # SCF fine-grained fields
    batch: SCFBatchInfo | None = None
    current_frame: SCFCurrentFrame | None = None
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
    """Response containing input parameters for a job."""

    available: bool
    incar: Dict[str, str] | None = None
    kpoints_text: str | None = None
    parameters: Dict[str, str] | None = None
    parameters_title: str | None = None
    warning: str | None = None


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

    potim_fs: float | None = None
    tebeg: float | None = None
    teend: float | None = None
    target_temperature: float | None = None
    temperature_tolerance_low: float | None = None
    temperature_tolerance_high: float | None = None
    mean_total_energy: float | None = None
    initial_total_energy: float | None = None
    energy_drift_slope_ev_per_step: float | None = None


class MDTimeseriesStats(BaseModel):
    """Summary statistics for the returned timeseries data."""

    current_step: int
    total_steps: int | None = None
    original_points: int
    returned_points: int
    sampled: bool


class JobMdTimeseriesResponse(BaseModel):
    """Response for the MD timeseries endpoint."""

    available: bool
    step_type: str | None = None
    state: str | None = None
    selected_attempt: int = 1
    attempts: List[MDAttemptItem] = Field(default_factory=list)
    series: MDSeriesData | None = None
    references: MDReferenceLines | None = None
    stats: MDTimeseriesStats | None = None
    warning: str | None = None
