"""
Pydantic models for frontend API responses and requests.

This module defines the data models for the frontend API layer,
implementing a dual-layer status model: raw status passthrough
plus derived status for UI consumption.
"""

from typing import Dict, List, Optional

from pydantic import BaseModel


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
    failed_job_names: List[str] = []


class TaskSummaryListResponse(BaseModel):
    """Response for task summary list endpoint."""

    total: int
    items: List[TaskSummary]


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
