"""
Frontend API Router.

This module provides the FastAPI router for frontend-facing endpoints,
implementing a unified response format and dependency injection pattern
to avoid circular imports with app.py.
"""

import asyncio
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response

from ..api_common import verify_task_ownership as api_verify_task_ownership
from ..auth.dependencies import get_current_user
from ..database import qdyndb
from ..main_workflow import MainWorkflow, QueryError, ValidationError
from . import service
from .models import (
    ComputeConstraintMaskRequest,
    ComputeConstraintMaskResponse,
    ContinueResultResponse,
    RenameTaskRequest,
    JobErrorResponse,
    JobFilesResponse,
    JobImagesResponse,
    JobInputParamsResponse,
    JobMdTimeseriesResponse,
    JobProgressResponse,
    JobStatusDetailResponse,
    StopFailedItem,
    StopResultResponse,
    StructureValidationInfo,
    StructureValidationRequest,
    StructureValidationResponse,
    SubdirFilesResponse,
    TaskJobsStatusResponse,
    TaskSummaryListResponse,
)

logger = logging.getLogger(__name__)


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

    def verify_job_belongs_to_task(task_id: str, job_uuid: str) -> None:
        """Verify that job_uuid belongs to the given task.

        Queries MainWorkflow.list_task_jobs() to collect all known job
        UUIDs for the task and raises HTTPException(404) if the job is
        not among them.  A 404 is also returned when the task itself
        does not exist (list_task_jobs raises ValidationError).

        Args:
            task_id: The task identifier.
            job_uuid: The job UUID to validate.

        Raises:
            HTTPException: 404 if the job is not part of the task.
        """
        manager = manager_getter()
        try:
            jobs_by_step = manager.list_task_jobs(task_id)
        except (QueryError, ValidationError) as exc:
            logger.warning(
                "Task %s not found when verifying job %s: %s",
                task_id, job_uuid, exc,
            )
            raise HTTPException(status_code=404, detail=str(exc))

        all_uuids = {
            uuid
            for uuid_list in jobs_by_step.values()
            for uuid in uuid_list
        }

        if job_uuid not in all_uuids:
            logger.warning(
                "Job %s does not belong to task %s", job_uuid, task_id,
            )
            raise HTTPException(
                status_code=404,
                detail=f"Job '{job_uuid}' not found in task '{task_id}'",
            )

    def handle_query_errors(func):
        """Decorator to convert QueryError to HTTP 404 and ValidationError to HTTP 422."""
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                result = func(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    return await result
                return result
            except QueryError as e:
                raise HTTPException(status_code=404, detail=str(e))
            except ValidationError as e:
                raise HTTPException(status_code=422, detail=f"Validation error: {e}")
        return wrapper

    # -------------------------------------------------------------------------
    # GET /frontend/tasks/summary - Task summary list
    # -------------------------------------------------------------------------

    @router.get(
        "/tasks/summary",
        response_model=TaskSummaryListResponse,
        summary="Get task summary list",
        description="Retrieve a list of task summaries for the authenticated user.",
    )
    def get_task_summaries(
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
    def get_task_detail(
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
    # GET /frontend/tasks/{task_id}/structure-preview - On-demand structure preview
    # -------------------------------------------------------------------------

    @router.get(
        "/tasks/{task_id}/structure-preview",
        summary="Get task structure preview",
        description=(
            "Compute structure preview on-demand for a task. "
            "Resolution order: queued payload -> first job run directory -> "
            "prev_task_id chain (max 10 hops)."
        ),
    )
    def get_task_structure_preview(
        task_id: str,
        username: str = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Compute structure preview on-demand for a task.

        Resolution order:
        1. Queued task: read input.stru + input.stru_format from queue payload
        2. Running/completed task: read structure file from first job's run directory
        3. Resume task with no own structure: trace prev_task_id chain (max 10 hops)

        Returns StructurePreviewPayload or null (wrapped in success response).
        """
        verify_task_ownership_local(task_id, username)

        manager = manager_getter()
        preview = service.compute_structure_preview(task_id, manager)
        if preview is None:
            logger.info("structure-preview for %s: no preview found", task_id)
        else:
            logger.info("structure-preview for %s: %d atoms", task_id, len(preview.species))
        return success_response(preview.model_dump() if preview else None)

    # -------------------------------------------------------------------------
    # GET /frontend/tasks/{task_id}/jobs/status - All job statuses
    # -------------------------------------------------------------------------

    @router.get(
        "/tasks/{task_id}/jobs/status",
        summary="Get all job statuses for a task",
        description="Retrieve the status of all jobs under a specific task.",
    )
    def get_task_jobs_status(
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
        description="Retrieve detailed status for a specific job. For detailed error info, use /error endpoint.",
    )
    @handle_query_errors
    def get_job_status_detail(
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
    # GET /frontend/tasks/{task_id}/jobs/{job_uuid}/error - Job error detail
    # -------------------------------------------------------------------------

    @router.get(
        "/tasks/{task_id}/jobs/{job_uuid}/error",
        response_model=JobErrorResponse,
        summary="Get job error details",
        description="Retrieve structured error information for a specific job.",
    )
    def get_job_error(
        task_id: str,
        job_uuid: str,
        username: str = Depends(get_current_user),
    ) -> JobErrorResponse:
        """
        Get structured error details for a failed job.

        Returns a structured object with state, availability flag,
        short message, and full traceback.

        Args:
            task_id: The task identifier.
            job_uuid: The job UUID to query.

        Returns:
            A JobErrorResponse with error details.
        """
        verify_task_ownership_local(task_id, username)

        try:
            return service.get_job_error_detail(task_id, job_uuid, manager_getter)
        except QueryError as e:
            # Convert "job not found in task" to 404
            if "not found in task" in str(e):
                raise HTTPException(status_code=404, detail=str(e))
            # Convert other query failures to 500
            else:
                raise HTTPException(status_code=500, detail=str(e))

    # -------------------------------------------------------------------------
    # POST /frontend/tasks/{task_id}/stop - Stop task
    # -------------------------------------------------------------------------

    @router.post(
        "/tasks/{task_id}/stop",
        response_model=StopResultResponse,
        summary="Stop a task",
        description="Stop all running/waiting jobs for a task. Returns per-job results.",
    )
    @handle_query_errors
    def stop_task(
        task_id: str,
        username: str = Depends(get_current_user),
    ) -> StopResultResponse:
        """
        Stop all stoppable jobs for a task.

        Jobs in COMPLETED, FAILED, or other terminal states are skipped.
        Returns lists of stopped, skipped, and failed-to-stop job UUIDs.

        Args:
            task_id: The task identifier.

        Returns:
            A StopResultResponse with per-job outcomes.
        """
        verify_task_ownership_local(task_id, username)

        manager = manager_getter()
        result = manager.stop_task_jobs(task_id)

        # Convert the dictionary result to StopResultResponse
        failed_items = [
            StopFailedItem(uuid=f["uuid"], error=f["error"])
            for f in result["failed"]
        ]

        return StopResultResponse(
            stopped=result["stopped"],
            skipped=result["skipped"],
            failed=failed_items,
        )

    # -------------------------------------------------------------------------
    # POST /frontend/tasks/{task_id}/continue - Continue task
    # -------------------------------------------------------------------------

    @router.post(
        "/tasks/{task_id}/continue",
        response_model=ContinueResultResponse,
        summary="Continue a task",
        description="Resume all paused/stopped jobs for a task. Returns per-job results.",
    )
    @handle_query_errors
    def continue_task(
        task_id: str,
        username: str = Depends(get_current_user),
    ) -> ContinueResultResponse:
        """
        Resume all paused/stopped jobs for a task.

        Jobs in COMPLETED, FAILED, or other terminal states are skipped.
        Returns lists of continued, skipped, and failed-to-resume job UUIDs.

        Args:
            task_id: The task identifier.

        Returns:
            A ContinueResultResponse with per-job outcomes.
        """
        verify_task_ownership_local(task_id, username)

        manager = manager_getter()
        result = manager.continue_task_jobs(task_id)

        failed_items = [
            StopFailedItem(uuid=f["uuid"], error=f["error"])
            for f in result["failed"]
        ]

        return ContinueResultResponse(
            continued=result["continued"],
            skipped=result["skipped"],
            failed=failed_items,
        )

    # -------------------------------------------------------------------------
    # DELETE /frontend/tasks/{task_id} - Delete task
    # -------------------------------------------------------------------------

    @router.delete(
        "/tasks/{task_id}",
        status_code=204,
        summary="Delete a task",
        description="Stop running jobs and delete local task records.",
    )
    @handle_query_errors
    def delete_task(
        task_id: str,
        username: str = Depends(get_current_user),
    ) -> Response:
        """
        Delete a task: stop all running jobs, then remove local records.

        If any job fails to stop, the local record is preserved and an
        error is returned with details about which jobs could not be stopped.

        Args:
            task_id: The task identifier.

        Returns:
            204 No Content on success.
        """
        verify_task_ownership_local(task_id, username)

        try:
            manager = manager_getter()
            manager.delete_task_record(task_id)
        except RuntimeError as exc:
            raise HTTPException(
                status_code=409,
                detail=str(exc),
            )

        return Response(status_code=204)

    # -------------------------------------------------------------------------
    # PATCH /frontend/tasks/{task_id}/name - Rename a task
    # -------------------------------------------------------------------------

    @router.patch(
        "/tasks/{task_id}/name",
        summary="Rename a task",
        description="Update the display name of a task.",
    )
    @handle_query_errors
    def rename_task(
        task_id: str,
        req: RenameTaskRequest,
        username: str = Depends(get_current_user),
    ):
        """
        Update the task_name in local metadata.

        Args:
            task_id: The task identifier.
            req: New task name (or null to clear).

        Returns:
            Success response with the updated name.
        """
        verify_task_ownership_local(task_id, username)

        name = req.task_name.strip() if req.task_name else None
        if not qdyndb.update_task_name(task_id, name):
            raise HTTPException(status_code=404, detail="Task not found")

        return success_response({"task_name": name})

    # -------------------------------------------------------------------------
    # POST /frontend/structures/validate - POSCAR validation
    # -------------------------------------------------------------------------

    @router.post(
        "/structures/validate",
        summary="Validate POSCAR structure",
        description="Pre-validate a POSCAR structure string before submission.",
    )
    def validate_structure(
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

            # Build 3D preview payload (best-effort; failure does not block validation)
            preview = None
            try:
                from .structure_preview import build_preview

                preview = build_preview(payload.content, fmt="vasp")
            except Exception as preview_exc:
                logger.warning(
                    "Structure preview generation failed: %s", preview_exc,
                )

            # Extract basic info for the response
            result = StructureValidationResponse(
                valid=True,
                structure=StructureValidationInfo(
                    num_atoms=len(atoms),
                    formula=atoms.get_chemical_formula(),
                    lattice=atoms.cell.array.tolist(),
                ),
                preview=preview,
            )
            return success_response(result.model_dump())

        except Exception as exc:
            return error_response(
                "PARSE_ERROR",
                f"Failed to parse structure: {str(exc)}",
            )

    # -------------------------------------------------------------------------
    # POST /frontend/compute-constraint-mask - Real-time constraint preview
    # -------------------------------------------------------------------------

    @router.post(
        "/compute-constraint-mask",
        response_model=ComputeConstraintMaskResponse,
        summary="Compute per-atom constraint mask",
        description=(
            "Compute a per-atom boolean constraint mask for structure preview. "
            "If the structure file already contains ASE constraints (e.g. selective "
            "dynamics), those take priority and are returned with source='file'. "
            "Otherwise, the mask is computed from the layer parameters."
        ),
    )
    def compute_constraint_mask(
        req: ComputeConstraintMaskRequest,
        username: str = Depends(get_current_user),
    ) -> ComputeConstraintMaskResponse:
        """Compute per-atom constraint mask for real-time preview.

        Follows the same priority as the runtime NVT/NVE logic:
        file-level constraints take precedence over layer-based constraints.

        Args:
            req: The constraint mask computation request payload.

        Returns:
            A ComputeConstraintMaskResponse with the computed mask.

        Raises:
            HTTPException: 422 if constraint parameters are invalid or
                layer detection fails.
        """
        import io

        import ase.io

        from .structure_preview import _extract_constraint_mask
        from ..tools.nvt import compute_layer_constraint_mask

        # Step 1: Parse structure
        try:
            atoms = ase.io.read(io.StringIO(req.stru_content), format=req.stru_format)
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Failed to parse structure: {exc}",
            )

        if atoms is None:
            raise HTTPException(
                status_code=422,
                detail="Failed to parse structure: ASE returned None",
            )

        # Step 2: Check file-level constraints (same priority as runtime)
        file_mask = _extract_constraint_mask(atoms)
        if file_mask is not None:
            return ComputeConstraintMaskResponse(
                constraint_mask=file_mask,
                source="file",
                warning=(
                    "Structure file already contains constraints "
                    "(e.g. selective dynamics). These take priority over "
                    "layer-based constraint parameters."
                ),
            )

        # Step 3: Compute layer-based constraint mask
        try:
            mask = compute_layer_constraint_mask(
                atoms,
                req.constraint_layers,
                req.layer_direction,
                req.total_layers,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            )

        return ComputeConstraintMaskResponse(
            constraint_mask=mask,
            source="layers",
        )

    # -------------------------------------------------------------------------
    # GET /frontend/tasks/{task_id}/jobs/{job_uuid}/files - List job files
    # -------------------------------------------------------------------------

    @router.get(
        "/tasks/{task_id}/jobs/{job_uuid}/files",
        response_model=JobFilesResponse,
        summary="List files in a job's run directory",
        description="Retrieve a list of whitelisted files from a job's run directory.",
    )
    def list_job_files_endpoint(
        task_id: str,
        job_uuid: str,
        username: str = Depends(get_current_user),
    ) -> JobFilesResponse:
        """
        List available files for a job.

        Args:
            task_id: The task identifier.
            job_uuid: The job UUID.

        Returns:
            A JobFilesResponse with file list or available=False.
        """
        verify_task_ownership_local(task_id, username)
        verify_job_belongs_to_task(task_id, job_uuid)

        manager = manager_getter()
        access = service.get_run_dir_access(job_uuid, manager)

        if access is None:
            return JobFilesResponse(available=False)

        files, subdirs = service.list_job_files(access, task_id, job_uuid)
        return JobFilesResponse(available=True, files=files, subdirs=subdirs)

    # -------------------------------------------------------------------------
    # GET /frontend/tasks/{task_id}/jobs/{job_uuid}/files/{filename} - Serve file
    # -------------------------------------------------------------------------

    @router.get(
        "/tasks/{task_id}/jobs/{job_uuid}/files/{filename}",
        summary="Download a file from a job's run directory",
        description="Serve a single whitelisted file from the job's run directory.",
    )
    def get_job_file_endpoint(
        task_id: str,
        job_uuid: str,
        filename: str,
        username: str = Depends(get_current_user),
    ) -> Response:
        """
        Serve a single file from a job's run directory.

        For local workers, returns a streaming FileResponse.
        For remote workers, downloads the file via SSH and returns
        an in-memory Response with the file bytes.

        Args:
            task_id: The task identifier.
            job_uuid: The job UUID.
            filename: The name of the file to retrieve.

        Returns:
            A FileResponse (local) or Response (remote) with the file contents.
        """
        verify_task_ownership_local(task_id, username)
        verify_job_belongs_to_task(task_id, job_uuid)

        manager = manager_getter()
        access = service.get_run_dir_access(job_uuid, manager)

        if access is None:
            raise HTTPException(status_code=404, detail="Job run directory not available")

        try:
            result, content_type = service.serve_job_file(access, filename)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

        from pathlib import Path as _Path

        if isinstance(result, _Path):
            return FileResponse(
                path=str(result),
                media_type=content_type,
                filename=filename,
            )
        else:
            # Remote: result is bytes
            return Response(
                content=result,
                media_type=content_type,
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"'
                },
            )

    # -------------------------------------------------------------------------
    # GET .../files/{subdir}/{filename} - Serve subdirectory file
    # -------------------------------------------------------------------------

    @router.get(
        "/tasks/{task_id}/jobs/{job_uuid}/files/{subdir}/{filename}",
        summary="Download a file from a job subdirectory",
        description=(
            "Serve a single file from an allowed subdirectory "
            "(e.g. scf_000/) within a job's run directory."
        ),
    )
    def get_job_subdir_file_endpoint(
        task_id: str,
        job_uuid: str,
        subdir: str,
        filename: str,
        username: str = Depends(get_current_user),
    ) -> Response:
        """
        Serve a file from a job's subdirectory (e.g. scf_000/OUTCAR).

        Only subdirectories with whitelisted prefixes (scf_, nvt_attempt_)
        are accessible.

        Args:
            task_id: The task identifier.
            job_uuid: The job UUID.
            subdir: The subdirectory name (e.g. "scf_000").
            filename: The file name within the subdirectory.

        Returns:
            A FileResponse (local) or Response (remote) with the file contents.
        """
        verify_task_ownership_local(task_id, username)
        verify_job_belongs_to_task(task_id, job_uuid)

        manager = manager_getter()
        access = service.get_run_dir_access(job_uuid, manager)

        if access is None:
            raise HTTPException(
                status_code=404, detail="Job run directory not available"
            )

        try:
            result, content_type = service.serve_subdir_file(
                access, subdir, filename
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

        from pathlib import Path as _Path

        if isinstance(result, _Path):
            return FileResponse(
                path=str(result),
                media_type=content_type,
                filename=filename,
            )
        else:
            return Response(
                content=result,
                media_type=content_type,
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"'
                },
            )

    # -------------------------------------------------------------------------
    # GET .../subdirs/{subdir}/files - List subdirectory files (lazy load)
    # -------------------------------------------------------------------------

    @router.get(
        "/tasks/{task_id}/jobs/{job_uuid}/subdirs/{subdir}/files",
        response_model=SubdirFilesResponse,
        summary="List files in a job subdirectory",
        description=(
            "Retrieve the file list for a specific subdirectory within "
            "a job's run directory. Used for lazy-loading subdirectory "
            "contents when the user expands a folder."
        ),
    )
    def list_subdir_files_endpoint(
        task_id: str,
        job_uuid: str,
        subdir: str,
        username: str = Depends(get_current_user),
    ) -> SubdirFilesResponse:
        """
        List files inside a specific subdirectory.

        Args:
            task_id: The task identifier.
            job_uuid: The job UUID.
            subdir: The subdirectory name (e.g. "scf_000").

        Returns:
            A SubdirFilesResponse with the file list.
        """
        verify_task_ownership_local(task_id, username)
        verify_job_belongs_to_task(task_id, job_uuid)

        manager = manager_getter()
        access = service.get_run_dir_access(job_uuid, manager)

        if access is None:
            return SubdirFilesResponse(
                available=False, subdir=subdir
            )

        try:
            files = service.list_subdir_files(
                access, task_id, job_uuid, subdir
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        return SubdirFilesResponse(
            available=True, subdir=subdir, files=files
        )

    # -------------------------------------------------------------------------
    # GET /frontend/tasks/{task_id}/jobs/{job_uuid}/progress - Job progress
    # -------------------------------------------------------------------------

    @router.get(
        "/tasks/{task_id}/jobs/{job_uuid}/progress",
        response_model=JobProgressResponse,
        summary="Get job progress",
        description="Retrieve progress information for a running or completed job.",
    )
    def get_job_progress_endpoint(
        task_id: str,
        job_uuid: str,
        username: str = Depends(get_current_user),
    ) -> JobProgressResponse:
        """
        Get progress for a job (MD steps or SCF convergence).

        Args:
            task_id: The task identifier.
            job_uuid: The job UUID.

        Returns:
            A JobProgressResponse with progress details.
        """
        verify_task_ownership_local(task_id, username)
        verify_job_belongs_to_task(task_id, job_uuid)

        manager = manager_getter()
        return service.get_job_progress(manager, job_uuid)

    # -------------------------------------------------------------------------
    # GET /frontend/tasks/{task_id}/jobs/{job_uuid}/input-params - Job input params
    # -------------------------------------------------------------------------

    @router.get(
        "/tasks/{task_id}/jobs/{job_uuid}/input-params",
        response_model=JobInputParamsResponse,
        summary="Get job input parameters",
        description="Retrieve parsed INCAR and KPOINTS for a specific job.",
    )
    def get_job_input_params_endpoint(
        task_id: str,
        job_uuid: str,
        username: str = Depends(get_current_user),
    ) -> JobInputParamsResponse:
        """
        Get INCAR key-value pairs and raw KPOINTS text for a job.

        Args:
            task_id: The task identifier.
            job_uuid: The job UUID.

        Returns:
            A JobInputParamsResponse with parsed input parameters.
        """
        verify_task_ownership_local(task_id, username)
        verify_job_belongs_to_task(task_id, job_uuid)

        manager = manager_getter()
        return service.get_job_input_params(manager, job_uuid)

    # -------------------------------------------------------------------------
    # GET /frontend/tasks/{task_id}/jobs/{job_uuid}/images - Job images
    # -------------------------------------------------------------------------

    @router.get(
        "/tasks/{task_id}/jobs/{job_uuid}/images",
        response_model=JobImagesResponse,
        summary="Get job result images",
        description="Retrieve result images for a completed job.",
    )
    def get_job_images_endpoint(
        task_id: str,
        job_uuid: str,
        username: str = Depends(get_current_user),
    ) -> JobImagesResponse:
        """
        Get result images for a completed job.

        Args:
            task_id: The task identifier.
            job_uuid: The job UUID.

        Returns:
            A JobImagesResponse with image list.
        """
        verify_task_ownership_local(task_id, username)
        verify_job_belongs_to_task(task_id, job_uuid)

        manager = manager_getter()
        return service.get_job_images(manager, task_id, job_uuid)

    # -------------------------------------------------------------------------
    # GET /frontend/tasks/{task_id}/jobs/{job_uuid}/md-timeseries
    # -------------------------------------------------------------------------

    @router.get(
        "/tasks/{task_id}/jobs/{job_uuid}/md-timeseries",
        response_model=JobMdTimeseriesResponse,
        summary="Get MD timeseries data",
        description="Retrieve full MD time-series data (temperature, energies) for NVT/NVE jobs.",
    )
    def get_job_md_timeseries_endpoint(
        task_id: str,
        job_uuid: str,
        attempt: int | None = Query(None, ge=1),
        max_points: int = Query(2000, ge=200, le=20000),
        username: str = Depends(get_current_user),
    ) -> JobMdTimeseriesResponse:
        """
        Get MD timeseries data for a job.

        Args:
            task_id: The task identifier.
            job_uuid: The job UUID.
            attempt: NVT attempt number (None = latest).
            max_points: Maximum data points to return.

        Returns:
            A JobMdTimeseriesResponse with timeseries data.
        """
        verify_task_ownership_local(task_id, username)
        verify_job_belongs_to_task(task_id, job_uuid)

        manager = manager_getter()
        return service.get_job_md_timeseries(manager, job_uuid, attempt, max_points)

    return router
