"""
Frontend API Router.

This module provides the FastAPI router for frontend-facing endpoints,
implementing a unified response format and dependency injection pattern
to avoid circular imports with app.py.
"""

from collections.abc import Callable
from typing import Any, Dict

from fastapi import APIRouter, Depends

from ..api_common import verify_task_ownership as api_verify_task_ownership
from ..auth.dependencies import get_current_user
from ..main_workflow import MainWorkflow
from . import service
from .models import (
    JobStatusDetailResponse,
    StructureValidationInfo,
    StructureValidationRequest,
    StructureValidationResponse,
    TaskJobsStatusResponse,
    TaskSummaryListResponse,
)


def create_frontend_router(manager_getter: Callable[[], MainWorkflow]) -> APIRouter:
    """
    Create and configure the frontend API router.

    This factory function accepts a manager_getter callable to inject
    the MainWorkflow instance, avoiding direct imports from app.py
    which would cause circular dependencies.

    Args:
        manager_getter: A callable that returns the MainWorkflow instance.

    Returns:
        A configured APIRouter with all /frontend/* endpoints.
    """
    router = APIRouter(prefix="/frontend", tags=["frontend"])

    # -------------------------------------------------------------------------
    # Helper: Unified response wrapper
    # -------------------------------------------------------------------------

    def success_response(data: Any) -> Dict[str, Any]:
        """Wrap data in the standard success response format."""
        return {"success": True, "data": data}

    def error_response(code: str, message: str) -> Dict[str, Any]:
        """Wrap error in the standard error response format."""
        return {
            "success": False,
            "error": {"code": code, "message": message},
        }

    def verify_task_ownership_local(task_id: str, username: str) -> None:
        """Verify that the task belongs to the user, raising HTTPException if not."""
        api_verify_task_ownership(task_id, username)

    # -------------------------------------------------------------------------
    # GET /frontend/tasks/summary - Task summary list
    # -------------------------------------------------------------------------

    @router.get(
        "/tasks/summary",
        response_model=TaskSummaryListResponse,
        summary="Get task summary list",
        description="Retrieve a list of task summaries for the authenticated user.",
    )
    async def get_task_summaries(
        username: str = Depends(get_current_user),
    ) -> TaskSummaryListResponse:
        """
        Get a list of task summaries for the current user.

        Returns:
            A unified response containing the total count and list of task summaries.
        """
        summaries = service.get_task_summary_list(username, manager_getter)
        result = TaskSummaryListResponse(
            total=len(summaries),
            items=summaries,
        )
        return result

    # -------------------------------------------------------------------------
    # GET /frontend/tasks/{task_id} - Task detail
    # -------------------------------------------------------------------------

    @router.get(
        "/tasks/{task_id}",
        response_model=TaskJobsStatusResponse,
        summary="Get task detail",
        description="Retrieve detailed status for all jobs under a specific task.",
    )
    async def get_task_detail(
        task_id: str,
        username: str = Depends(get_current_user),
    ) -> TaskJobsStatusResponse:
        """
        Get detailed status for all jobs under a task.

        Args:
            task_id: The task identifier.

        Returns:
            A unified response containing the task's job status information.
        """
        verify_task_ownership_local(task_id, username)

        detail = service.get_task_detail(task_id, manager_getter)
        return detail

    # -------------------------------------------------------------------------
    # GET /frontend/tasks/{task_id}/jobs/status - All job statuses
    # -------------------------------------------------------------------------

    @router.get(
        "/tasks/{task_id}/jobs/status",
        summary="Get all job statuses for a task",
        description="Retrieve the status of all jobs under a specific task.",
    )
    async def get_task_jobs_status(
        task_id: str,
        username: str = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """
        Get status of all jobs under a task.

        This endpoint reuses get_task_detail but returns a simplified view
        focused on job status aggregation.

        Args:
            task_id: The task identifier.

        Returns:
            A unified response containing job status summary.
        """
        verify_task_ownership_local(task_id, username)

        detail = service.get_task_detail(task_id, manager_getter)
        return success_response(detail.model_dump())

    # -------------------------------------------------------------------------
    # GET /frontend/tasks/{task_id}/jobs/{job_uuid}/status - Single job status
    # -------------------------------------------------------------------------

    @router.get(
        "/tasks/{task_id}/jobs/{job_uuid}/status",
        summary="Get single job status",
        description="Retrieve detailed status for a specific job, including error summary if failed.",
    )
    async def get_job_status_detail(
        task_id: str,
        job_uuid: str,
        username: str = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """
        Get detailed status for a single job.

        This endpoint returns the job's state, derived state for UI display,
        and an error summary if the job has failed.

        Args:
            task_id: The task identifier.
            job_uuid: The job UUID to query.

        Returns:
            A unified response containing the job's detailed status.
        """
        verify_task_ownership_local(task_id, username)

        # Get basic job info
        job_info = service.get_job_info_safe(task_id, job_uuid, manager_getter)

        # Get error summary if the job is in an error/failed state
        error_summary = None
        if job_info.state in ["FAILED", "ERROR", "REMOTE_ERROR"]:
            error_summary = service.get_job_error_summary(
                task_id, job_uuid, manager_getter
            )

        # Build the detailed response
        detail = JobStatusDetailResponse(
            uuid=job_uuid,
            name=job_info.name,
            state=job_info.state,
            derived_state=service.derive_job_state(job_info.state),
            error=error_summary,
            log_note="Full logs are available via the compute node filesystem",
        )

        return success_response(detail.model_dump())

    # -------------------------------------------------------------------------
    # POST /frontend/structures/validate - POSCAR validation
    # -------------------------------------------------------------------------

    @router.post(
        "/structures/validate",
        summary="Validate POSCAR structure",
        description="Pre-validate a POSCAR structure string before submission.",
    )
    async def validate_structure(
        payload: StructureValidationRequest,
        username: str = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """
        Validate a POSCAR structure string.

        This endpoint performs local validation of a POSCAR format structure
        before task submission, checking for parseability and basic integrity.

        Args:
            payload: The POSCAR validation request payload.

        Returns:
            A unified response with validation result.
        """
        import io

        import ase.io

        try:
            # Attempt to parse the structure with ASE
            atoms = ase.io.read(io.StringIO(payload.content), format="vasp")

            # Basic validation checks
            if atoms is None:
                return error_response(
                    "PARSE_ERROR",
                    "Failed to parse structure: ASE returned None",
                )

            # Extract basic info for the response
            result = StructureValidationResponse(
                valid=True,
                structure=StructureValidationInfo(
                    num_atoms=len(atoms),
                    formula=atoms.get_chemical_formula(),
                    lattice=atoms.cell.array.tolist(),
                ),
            )
            return success_response(result.model_dump())

        except Exception as exc:
            return error_response(
                "PARSE_ERROR",
                f"Failed to parse structure: {str(exc)}",
            )

    return router
