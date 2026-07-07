"""
Shared helper functions for QDYN API modules.

This module provides common utilities used across multiple API routers,
avoiding circular dependencies with app.py.
"""

from fastapi import HTTPException, status

from .database import qdyndb


def verify_task_ownership(task_id: str, username: str) -> str:
    """
    Verify that a task belongs to the specified user.

    Returns the owner string on success so callers can reuse it without
    issuing a second ``get_task_owner`` query.  Existing callers that
    ignore the return value are unaffected.

    Args:
        task_id: The task identifier to check.
        username: The username to verify ownership against.

    Returns:
        The verified owner username.

    Raises:
        HTTPException: 404 if task not found, 403 if access denied.
    """
    owner = qdyndb.get_task_owner(task_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if owner != username:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    return owner


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
