"""
Shared helper functions for QDYN API modules.

This module provides common utilities used across multiple API routers,
avoiding circular dependencies with app.py.
"""

from fastapi import HTTPException, status

from .database import qdyndb


def verify_task_ownership(task_id: str, username: str) -> None:
    """
    Verify that a task belongs to the specified user.

    Admin users (is_admin=True in DB) bypass the ownership check
    and can access any task.  This allows admins to use the regular
    /frontend/* endpoints for file browsing, progress, etc.

    Args:
        task_id: The task identifier to check.
        username: The username to verify ownership against.

    Raises:
        HTTPException: 404 if task not found, 403 if access denied.
    """
    owner = qdyndb.get_task_owner(task_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if owner != username:
        # Allow admin users to access any task
        user = qdyndb.get_user(username)
        if user and user.get("is_admin"):
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )


def get_task_or_404(task_id: str) -> dict:
    """
    Get task information or raise 404 if not found.

    Args:
        task_id: The task identifier to retrieve.

    Returns:
        dict: Task ownership information including task_id, username, and job_ids.

    Raises:
        HTTPException: 404 if task not found.
    """
    owner = qdyndb.get_task_owner(task_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="Task not found")

    job_ids = qdyndb.get_task_job_ids(task_id)
    return {
        "task_id": task_id,
        "username": owner,
        "job_ids": job_ids,
    }
