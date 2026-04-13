"""Admin API router.

Uses a factory function to inject the MainWorkflow instance,
following the same pattern as frontend_api/router.py.
"""

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from ..auth.dependencies import get_current_admin
from ..frontend_api.models import (
    ContinueResultResponse,
    StopFailedItem,
    StopResultResponse,
)
from ..main_workflow import MainWorkflow
from . import service
from .models import (
    AdminStatsResponse,
    AdminTaskListResponse,
    AdminUserItem,
    AdminWorkerItem,
    FileDeleteRequest,
    FileDeleteResponse,
    FileNameDeleteRequest,
)


class PasswordResetRequest(BaseModel):
    """Request body for password reset."""

    password: str


class RoleUpdateRequest(BaseModel):
    """Request body for role update."""

    is_admin: bool


def create_admin_router(
    manager_getter: Callable[[], MainWorkflow],
) -> APIRouter:
    """Create and configure the admin API router.

    Args:
        manager_getter: A callable that returns the MainWorkflow instance.

    Returns:
        A configured APIRouter with all /api/admin/* endpoints.
    """
    router = APIRouter(
        prefix="/api/admin",
        tags=["admin"],
        dependencies=[Depends(get_current_admin)],
    )

    # -----------------------------------------------------------------
    # GET /api/admin/stats
    # -----------------------------------------------------------------

    @router.get("/stats", response_model=AdminStatsResponse)
    def get_stats() -> AdminStatsResponse:
        """Return admin dashboard statistics."""
        data = service.get_admin_stats(manager_getter)
        return AdminStatsResponse(**data)

    # -----------------------------------------------------------------
    # GET /api/admin/users
    # -----------------------------------------------------------------

    @router.get("/users", response_model=list[AdminUserItem])
    def list_users() -> list[AdminUserItem]:
        """Return all users with task counts."""
        users = service.get_all_users()
        return [AdminUserItem(**u) for u in users]

    # -----------------------------------------------------------------
    # PUT /api/admin/users/{username}/password
    # -----------------------------------------------------------------

    @router.put("/users/{username}/password")
    def reset_password(
        username: str,
        body: PasswordResetRequest,
    ) -> dict[str, bool]:
        """Reset a user's password."""
        service.reset_user_password(username, body.password)
        return {"ok": True}

    # -----------------------------------------------------------------
    # PUT /api/admin/users/{username}/role
    # -----------------------------------------------------------------

    @router.put("/users/{username}/role")
    def update_role(
        username: str,
        body: RoleUpdateRequest,
        admin: str = Depends(get_current_admin),
    ) -> dict[str, bool]:
        """Set or revoke admin role for a user."""
        service.set_user_role(username, body.is_admin, admin)
        return {"ok": True}

    # -----------------------------------------------------------------
    # DELETE /api/admin/users/{username}
    # -----------------------------------------------------------------

    @router.delete("/users/{username}", status_code=204)
    def delete_user(
        username: str,
        admin: str = Depends(get_current_admin),
    ) -> Response:
        """Delete a user with full cascade.

        The ``admin`` parameter captures the current admin's username
        (separate from the route-level dependency) so the service layer
        can prevent self-deletion.
        """
        service.delete_user(username, manager_getter, admin)
        return Response(status_code=204)

    # -----------------------------------------------------------------
    # GET /api/admin/tasks
    # -----------------------------------------------------------------

    @router.get("/tasks", response_model=AdminTaskListResponse)
    def list_tasks(
        owner: str | None = Query(None),
        status: str | None = Query(None),
    ) -> AdminTaskListResponse:
        """Return a global task list (all users), with optional filters."""
        items = service.get_all_task_summaries(
            manager_getter,
            owner_filter=owner,
            status_filter=status,
        )
        return AdminTaskListResponse(total=len(items), items=items)

    # -----------------------------------------------------------------
    # GET /api/admin/tasks/{task_id}/detail
    # -----------------------------------------------------------------

    @router.get("/tasks/{task_id}/detail")
    def get_task_detail(task_id: str) -> dict:
        """Return job-level detail for a task (bypasses ownership check)."""
        from ..frontend_api import service as fe_service

        detail = fe_service.get_task_detail(task_id, manager_getter)
        return detail.model_dump()

    # -----------------------------------------------------------------
    # GET /api/admin/tasks/{task_id}/work-dir
    # -----------------------------------------------------------------

    @router.get("/tasks/{task_id}/work-dir")
    def get_task_work_dir(task_id: str) -> dict[str, str | None]:
        """Return the run_dir of a task's first job."""
        work_dir = service.get_task_work_dir(task_id, manager_getter)
        return {"work_dir": work_dir}

    # -----------------------------------------------------------------
    # POST /api/admin/tasks/{task_id}/stop
    # -----------------------------------------------------------------

    @router.post(
        "/tasks/{task_id}/stop", response_model=StopResultResponse
    )
    def stop_task(
        task_id: str,
        admin: str = Depends(get_current_admin),
    ) -> StopResultResponse:
        """Stop all stoppable jobs for a task (admin action)."""
        result = service.admin_stop_task(task_id, manager_getter, admin)
        failed_items = [
            StopFailedItem(uuid=f["uuid"], error=f["error"])
            for f in result["failed"]
        ]
        return StopResultResponse(
            stopped=result["stopped"],
            skipped=result["skipped"],
            failed=failed_items,
        )

    # -----------------------------------------------------------------
    # POST /api/admin/tasks/{task_id}/continue
    # -----------------------------------------------------------------

    @router.post(
        "/tasks/{task_id}/continue",
        response_model=ContinueResultResponse,
    )
    def continue_task(
        task_id: str,
        admin: str = Depends(get_current_admin),
    ) -> ContinueResultResponse:
        """Resume all paused/stopped jobs for a task (admin action)."""
        result = service.admin_continue_task(
            task_id, manager_getter, admin
        )
        failed_items = [
            StopFailedItem(uuid=f["uuid"], error=f["error"])
            for f in result["failed"]
        ]
        return ContinueResultResponse(
            continued=result["continued"],
            skipped=result["skipped"],
            failed=failed_items,
        )

    # -----------------------------------------------------------------
    # DELETE /api/admin/tasks/{task_id}
    # -----------------------------------------------------------------

    @router.delete("/tasks/{task_id}", status_code=204)
    def delete_task(
        task_id: str,
        cleanup_dirs: bool = Query(True, description="Delete run directories on disk"),
        admin: str = Depends(get_current_admin),
    ) -> Response:
        """Delete a task with optional work_dir cleanup (admin action)."""
        service.admin_delete_task(task_id, manager_getter, admin, cleanup_dirs=cleanup_dirs)
        return Response(status_code=204)

    # -----------------------------------------------------------------
    # GET /api/admin/files
    # -----------------------------------------------------------------

    @router.get("/files")
    def list_work_dirs(
        refresh: bool = Query(False, description="Force cache refresh"),
    ) -> dict:
        """List job directories under work_dir_base with task mapping."""
        if refresh:
            service.invalidate_files_cache()
        return service.list_work_dir_entries(manager_getter)

    # -----------------------------------------------------------------
    # POST /api/admin/files/delete
    # -----------------------------------------------------------------

    @router.post("/files/delete", response_model=FileDeleteResponse)
    def delete_files(body: FileDeleteRequest) -> FileDeleteResponse:
        """Bulk delete job directories or individual files."""
        result = service.delete_files(
            targets=[t.model_dump() for t in body.targets],
            delete_associated_tasks=body.delete_associated_tasks,
            manager_getter=manager_getter,
        )
        return FileDeleteResponse(**result)

    # -----------------------------------------------------------------
    # POST /api/admin/files/delete-by-name
    # -----------------------------------------------------------------

    @router.post(
        "/files/delete-by-name", response_model=FileDeleteResponse
    )
    def delete_files_by_name(
        body: FileNameDeleteRequest,
    ) -> FileDeleteResponse:
        """Delete a specific file from multiple job directories."""
        result = service.delete_files_by_name(
            filename=body.filename,
            job_dirs=body.job_dirs,
            manager_getter=manager_getter,
        )
        return FileDeleteResponse(**result)

    # -----------------------------------------------------------------
    # GET /api/admin/pool/workers
    # -----------------------------------------------------------------

    @router.get("/pool/workers", response_model=list[AdminWorkerItem])
    def list_workers() -> list[AdminWorkerItem]:
        """Return per-worker status, current user, and active job count."""
        workers = service.get_worker_details(manager_getter)
        return [AdminWorkerItem(**w) for w in workers]

    return router
