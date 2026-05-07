"""
Frontend API module for QDYN.

This module provides API endpoints specifically designed for the web frontend,
including task summaries, job status, and structure validation.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .models import (
    JobErrorResponse,
    JobStatusItem,
    JobStatusDetailResponse,
    StopFailedItem,
    StopResultResponse,
    TaskJobsStatusResponse,
    TaskSummary,
    TaskSummaryListResponse,
)

if TYPE_CHECKING:
    from .router import create_frontend_router as _create_frontend_router


def create_frontend_router(*args: Any, **kwargs: Any):
    from .router import create_frontend_router as _create_frontend_router

    return _create_frontend_router(*args, **kwargs)

__all__ = [
    "create_frontend_router",
    "JobErrorResponse",
    "JobStatusItem",
    "JobStatusDetailResponse",
    "StopFailedItem",
    "StopResultResponse",
    "TaskJobsStatusResponse",
    "TaskSummary",
    "TaskSummaryListResponse",
]
