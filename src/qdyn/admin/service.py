"""Business logic for the admin API.

All functions that need MainWorkflow access receive it via a
``manager_getter`` callable to avoid circular imports with app.py.
"""

import json
import logging
import os
import re
import shutil
import time as _time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List

from fastapi import HTTPException

from ..database import qdyndb
from ..frontend_api.models import TaskSummary
from ..main_workflow import MainWorkflow

if TYPE_CHECKING:
    from .storage_cache import StorageCache

logger = logging.getLogger(__name__)

# Canonical step ordering (same as frontend_api/service.py)
_STEP_ORDER = ["nvt", "nve", "scf", "pre_namd", "namd"]

# Module-level reference to the StorageCache singleton.
# Populated by app.py lifespan after creating the cache instance.
_storage_cache: "StorageCache | None" = None

# Cached result for list_work_dir_entries (avoids re-scanning on every request).
_files_cache: dict | None = None
_files_cache_time: float = 0
_FILES_CACHE_TTL: float = 300  # 5 minutes


def set_storage_cache(cache: "StorageCache") -> None:
    """Inject the StorageCache instance (called from app.py lifespan)."""
    global _storage_cache
    _storage_cache = cache


def invalidate_files_cache() -> None:
    """Force files cache refresh on next request (call after delete ops)."""
    global _files_cache, _files_cache_time
    _files_cache = None
    _files_cache_time = 0


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def get_admin_stats(manager_getter: Callable[[], MainWorkflow]) -> dict:
    """Compute dashboard statistics for the admin panel.

    Returns a dict matching the AdminStatsResponse fields.
    """
    manager = manager_getter()

    # User and task counts
    users = qdyndb.list_users()
    total_users = len(users)

    all_tasks = qdyndb.get_all_task_owners()
    total_tasks = len(all_tasks)

    # Running tasks: at least one non-terminal job in MongoDB
    running_tasks = 0
    try:
        jc = manager._ensure_job_controller()
        # Get unique flow UUIDs with at least one non-terminal job
        pipeline = [
            {"$match": {"state": {"$nin": MainWorkflow._TERMINAL_STATES}}},
            {"$group": {"_id": "$db_id"}},  # db_id groups by flow
        ]
        # Instead, count distinct task_ids that have non-terminal jobs.
        # task_ids are stored as uuid in the flow, mapped via our job_ids dict.
        # Simpler: count tasks where any job UUID is non-terminal.
        all_task_job_uuids: list[str] = []
        task_uuid_to_id: dict[str, str] = {}
        for task in all_tasks:
            job_ids = json.loads(task["job_ids"]) if task["job_ids"] else {}
            for uuid_list in job_ids.values():
                for uid in uuid_list:
                    all_task_job_uuids.append(uid)
                    task_uuid_to_id[uid] = task["task_id"]

        if all_task_job_uuids:
            # Find non-terminal jobs among our tracked UUIDs
            pipeline = [
                {
                    "$match": {
                        "uuid": {"$in": all_task_job_uuids},
                        "state": {"$nin": MainWorkflow._TERMINAL_STATES},
                    }
                },
                {"$group": {"_id": "$uuid"}},
            ]
            non_terminal_uuids = {
                doc["_id"] for doc in jc.jobs.aggregate(pipeline)
            }
            running_task_ids = {
                task_uuid_to_id[uid]
                for uid in non_terminal_uuids
                if uid in task_uuid_to_id
            }
            running_tasks = len(running_task_ids)
    except Exception as exc:
        logger.warning("Failed to count running tasks: %s", exc)

    # Queued tasks
    all_queued = qdyndb.list_all_queued()
    queued_tasks = len(all_queued)

    # Storage: read from background cache if available
    storage_bytes: int | None = None
    traj_storage_bytes: int | None = None
    traj_file_count = 0

    if _storage_cache is not None:
        storage_bytes = _storage_cache.get_total_work_dir_size()
        traj_storage_bytes, traj_file_count = _storage_cache.get_traj_stats()
    else:
        # Fallback: compute traj stats inline (work_dir stays None)
        try:
            user_data_dir = str(
                Path(
                    manager.config["basic"].get("user_data", "data/user_data")
                ).resolve()
            )
            traj_dir = os.path.join(user_data_dir, "trajs")
            if os.path.isdir(traj_dir):
                traj_storage_bytes, traj_file_count = _dir_size_and_count(
                    traj_dir
                )
        except Exception as exc:
            logger.warning("Failed to compute traj storage: %s", exc)

    return {
        "total_users": total_users,
        "total_tasks": total_tasks,
        "running_tasks": running_tasks,
        "queued_tasks": queued_tasks,
        "storage_bytes": storage_bytes,
        "traj_storage_bytes": traj_storage_bytes,
        "traj_file_count": traj_file_count,
    }


def _dir_size(path: str) -> int:
    """Recursively compute total size of a directory using os.scandir()."""
    total = 0
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                    elif entry.is_dir(follow_symlinks=False):
                        total += _dir_size(entry.path)
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _dir_size_and_count(path: str) -> tuple[int, int]:
    """Recursively compute total size and file count of a directory."""
    total_size = 0
    total_count = 0
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if entry.is_file(follow_symlinks=False):
                        total_size += entry.stat(follow_symlinks=False).st_size
                        total_count += 1
                    elif entry.is_dir(follow_symlinks=False):
                        sub_size, sub_count = _dir_size_and_count(entry.path)
                        total_size += sub_size
                        total_count += sub_count
                except OSError:
                    pass
    except OSError:
        pass
    return total_size, total_count


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------


def get_all_users() -> list[dict]:
    """Return all users with their task counts."""
    users = qdyndb.list_users()
    result = []
    for user in users:
        task_count = qdyndb.count_user_tasks(user["username"])
        result.append(
            {
                "username": user["username"],
                "is_admin": bool(user.get("is_admin")),
                "created_at": user["created_at"],
                "task_count": task_count,
            }
        )
    return result


def reset_user_password(
    username: str, new_password: str, admin_username: str = "system"
) -> None:
    """Reset a user's password (admin action)."""
    from ..auth.security import hash_password

    user = qdyndb.get_user(username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    hashed = hash_password(new_password)
    qdyndb.update_password(username, hashed)
    qdyndb.log_audit(admin_username, "admin_reset_password", target=username)


def set_user_role(
    username: str, is_admin: bool, admin_username: str
) -> None:
    """Set or revoke admin role for a user.

    Prevents revoking the last admin or self-demotion.
    """
    user = qdyndb.get_user(username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Guard: prevent self-demotion
    if not is_admin and username == admin_username:
        raise HTTPException(
            status_code=409,
            detail="Cannot revoke your own admin privileges.",
        )

    # Guard: prevent revoking the last admin
    if not is_admin and user.get("is_admin"):
        all_users = qdyndb.list_users()
        admin_count = sum(1 for u in all_users if u.get("is_admin"))
        if admin_count <= 1:
            raise HTTPException(
                status_code=409,
                detail="Cannot revoke the last admin. Promote another user first.",
            )

    qdyndb.set_admin(username, is_admin)
    qdyndb.log_audit(
        admin_username,
        "admin_set_role",
        target=username,
        detail=f"is_admin={is_admin}",
    )


def delete_user(
    username: str,
    manager_getter: Callable[[], MainWorkflow],
    admin_username: str,
) -> None:
    """Delete a user with full cascade.

    Parameters
    ----------
    username : str
        The user to delete.
    manager_getter : callable
        Returns the MainWorkflow instance.
    admin_username : str
        The admin performing the deletion (from Depends(get_current_admin)).
        Used to prevent self-deletion.

    Raises
    ------
    HTTPException
        403 if trying to delete self or last admin.
        404 if user not found.
        409 if user has DISPATCHING tasks.
    """
    # 1. Prevent self-deletion
    if username == admin_username:
        raise HTTPException(
            status_code=403,
            detail="Cannot delete your own account",
        )

    # 2. Check user exists
    user = qdyndb.get_user(username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # 3. Prevent deleting the last admin
    if user.get("is_admin"):
        all_users = qdyndb.list_users()
        admin_count = sum(1 for u in all_users if u.get("is_admin"))
        if admin_count <= 1:
            raise HTTPException(
                status_code=403,
                detail="Cannot delete the last admin user",
            )

    # 4. Check for DISPATCHING tasks
    queued_entries = qdyndb.list_queued_for_user(username)
    dispatching = [
        e for e in queued_entries if e["status"] == "DISPATCHING"
    ]
    if dispatching:
        raise HTTPException(
            status_code=409,
            detail=(
                f"User '{username}' has {len(dispatching)} task(s) currently "
                f"being dispatched. Please wait and try again."
            ),
        )

    manager = manager_getter()

    # 5. Cancel all QUEUED tasks for this user
    for entry in queued_entries:
        if entry["status"] == "QUEUED":
            conn = qdyndb.get_db()
            with qdyndb._lock:
                conn.execute(
                    "UPDATE queued_submissions SET status = 'CANCELLED' "
                    "WHERE task_id = ? AND status = 'QUEUED'",
                    (entry["task_id"],),
                )
                conn.commit()

    # 6. Stop all running tasks for this user — abort if any fail
    user_task_ids = qdyndb.get_user_tasks(username)
    stop_failures: list[str] = []
    for task_id in user_task_ids:
        if task_id in manager.task_ids:
            try:
                result = manager.stop_task_jobs(task_id)
                if result.get("failed"):
                    stop_failures.extend(
                        f"{f['uuid']}: {f['error']}" for f in result["failed"]
                    )
            except Exception as exc:
                stop_failures.append(f"task {task_id}: {exc}")

    if stop_failures:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot delete user '{username}': failed to stop some jobs. "
                f"Details: {'; '.join(stop_failures[:5])}"
            ),
        )

    # 7. Clean up MainWorkflow in-memory state
    for task_id in user_task_ids:
        if task_id in manager.task_ids:
            manager.task_ids.remove(task_id)
        if task_id in manager.job_ids:
            del manager.job_ids[task_id]

    # 8. Delete queued_submissions records
    qdyndb.delete_user_queued(username)

    # 9. Delete task_owners records
    qdyndb.delete_user_tasks(username)

    # 10. Delete user record
    qdyndb.delete_user_record(username)

    qdyndb.log_audit(admin_username, "admin_delete_user", target=username)
    logger.info("User '%s' deleted by admin '%s'.", username, admin_username)


# ---------------------------------------------------------------------------
# Task list (all users)
# ---------------------------------------------------------------------------


def get_all_task_summaries(
    manager_getter: Callable[[], MainWorkflow],
    owner_filter: str | None = None,
    status_filter: str | None = None,
) -> list[TaskSummary]:
    """Return task summaries across all users.

    Replicates the logic of frontend_api/service.py::get_task_summary_list()
    but without restricting to a single user.

    Parameters
    ----------
    owner_filter : str, optional
        Filter by task owner username.
    status_filter : str, optional
        Filter by derived status (e.g. "RUNNING", "FAILED").
    """
    all_tasks = qdyndb.get_all_task_owners()

    # Apply owner filter at the DB level
    if owner_filter:
        all_tasks = [t for t in all_tasks if t["username"] == owner_filter]

    # Build queued map across all users
    conn = qdyndb.get_db()
    with qdyndb._lock:
        queued_rows = conn.execute(
            "SELECT task_id, username, pool_name, status, created_at, last_error "
            "FROM queued_submissions "
            "WHERE status IN ('QUEUED', 'DISPATCHING', 'FAILED', 'CANCELLED') "
            "ORDER BY created_at ASC"
        ).fetchall()
    queued_map: Dict[str, dict] = {
        row["task_id"]: dict(row) for row in queued_rows
    }

    # Fix: if FAILED but task has real jobs, remove from queued_map
    failed_but_submitted = []
    for tid, entry in queued_map.items():
        if entry["status"] == "FAILED":
            real_job_ids = qdyndb.get_task_job_ids(tid)
            if real_job_ids:
                failed_but_submitted.append(tid)
    for tid in failed_but_submitted:
        del queued_map[tid]

    # Queue positions (global, across all users)
    all_queued = qdyndb.list_all_queued()
    queue_positions: Dict[str, int] = {
        q["task_id"]: i + 1 for i, q in enumerate(all_queued)
    }

    summaries: list[TaskSummary] = []

    for task_row in all_tasks:
        task_id = task_row["task_id"]
        username = task_row["username"]

        if task_id in queued_map:
            summary = _build_queued_task_summary(
                task_id, username, queued_map[task_id], queue_positions
            )
        else:
            summary = _build_task_summary(task_id, username, manager_getter)

        if summary is not None:
            if status_filter and summary.derived_status != status_filter:
                continue
            summaries.append(summary)

    return summaries


def _build_queued_task_summary(
    task_id: str,
    username: str,
    queue_entry: dict,
    queue_positions: Dict[str, int],
) -> TaskSummary:
    """Build a TaskSummary for a task still in the waiting queue."""
    meta = qdyndb.get_task_metadata(task_id) or {}

    created_at: float = _time.time()
    try:
        dt = datetime.strptime(
            queue_entry["created_at"], "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=timezone.utc)
        created_at = dt.timestamp()
    except Exception:
        pass

    queue_status = queue_entry["status"]
    _QUEUE_DERIVED_STATUS = {
        "QUEUED": "QUEUED",
        "DISPATCHING": "DISPATCHING",
        "FAILED": "FAILED",
        "CANCELLED": "CANCELLED",
    }
    derived_status = _QUEUE_DERIVED_STATUS.get(queue_status, queue_status)

    return TaskSummary(
        task_id=task_id,
        owner=username,
        created_at=created_at,
        raw_status_counts={},
        derived_status=derived_status,
        total_jobs=0,
        failed_job_names=[],
        steps=[],
        completed_steps=[],
        formula=meta.get("formula"),
        num_atoms=meta.get("num_atoms"),
        prev_task_id=meta.get("prev_task_id"),
        worker=meta.get("worker"),
        resume_next_step=None,
        resume_eligible=False,
        queue_status=queue_status,
        queue_position=queue_positions.get(task_id),
        pool_name=queue_entry.get("pool_name") or meta.get("pool_name"),
        runtime_worker=None,
    )


def _build_task_summary(
    task_id: str,
    username: str,
    manager_getter: Callable[[], MainWorkflow],
) -> TaskSummary | None:
    """Build a TaskSummary for a submitted task.

    Mirrors frontend_api/service.py::_build_task_summary() but takes an
    explicit username (from task_owners) instead of querying for it.
    """
    from ..frontend_api.service import derive_task_status

    job_ids = qdyndb.get_task_job_ids(task_id)

    raw_status_counts: Dict[str, int] = {}
    total_jobs = 0
    failed_job_names: List[str] = []
    step_all_completed: Dict[str, bool] = {}

    for step_name, uuid_list in job_ids.items():
        all_completed_for_step = True
        for idx, job_uuid in enumerate(uuid_list):
            total_jobs += 1
            try:
                manager = manager_getter()
                raw_state = manager.get_job_status(job_uuid)
                raw_status_counts[raw_state] = (
                    raw_status_counts.get(raw_state, 0) + 1
                )
                if raw_state == "FAILED":
                    failed_job_names.append(f"{step_name}_{idx}")
                if raw_state != "COMPLETED":
                    all_completed_for_step = False
            except Exception:
                raw_status_counts["ERROR"] = (
                    raw_status_counts.get("ERROR", 0) + 1
                )
                all_completed_for_step = False

        step_all_completed[step_name] = all_completed_for_step

    steps = [s for s in _STEP_ORDER if s in job_ids]

    completed_steps: List[str] = []
    for s in steps:
        if step_all_completed.get(s, False):
            completed_steps.append(s)
        else:
            break

    resume_next_step: str | None = None
    if completed_steps:
        last_completed = completed_steps[-1]
        last_idx = _STEP_ORDER.index(last_completed)
        if last_idx + 1 < len(_STEP_ORDER):
            resume_next_step = _STEP_ORDER[last_idx + 1]

    created_at = _get_task_created_at(task_id)
    derived_status = derive_task_status(raw_status_counts)

    resume_eligible = (
        resume_next_step is not None
        and derived_status in ("COMPLETED", "FAILED")
    )

    meta = qdyndb.get_task_metadata(task_id) or {}

    return TaskSummary(
        task_id=task_id,
        owner=username,
        created_at=created_at,
        raw_status_counts=raw_status_counts,
        derived_status=derived_status,
        total_jobs=total_jobs,
        failed_job_names=failed_job_names,
        steps=steps,
        completed_steps=completed_steps,
        formula=meta.get("formula"),
        num_atoms=meta.get("num_atoms"),
        prev_task_id=meta.get("prev_task_id"),
        worker=meta.get("worker"),
        resume_next_step=resume_next_step,
        resume_eligible=resume_eligible,
        pool_name=meta.get("pool_name"),
        runtime_worker=meta.get("worker"),
    )


def _get_task_created_at(task_id: str) -> float:
    """Get the creation timestamp for a task."""
    try:
        conn = qdyndb.get_db()
        row = conn.execute(
            "SELECT created_at FROM task_owners WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if row:
            dt = datetime.strptime(
                row["created_at"], "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=timezone.utc)
            return dt.timestamp()
    except Exception:
        pass
    return _time.time()


# ---------------------------------------------------------------------------
# Work dir
# ---------------------------------------------------------------------------


def get_task_work_dir(
    task_id: str, manager_getter: Callable[[], MainWorkflow]
) -> str | None:
    """Get the run_dir of a task's first job.

    For submitted tasks, queries jc.get_job_info(first_job_uuid).run_dir.
    For queued tasks or tasks with no jobs, returns None.
    """
    job_ids = qdyndb.get_task_job_ids(task_id)
    if not job_ids:
        return None

    # Get the first job UUID (first step, first job)
    for step in _STEP_ORDER:
        if step in job_ids and job_ids[step]:
            first_uuid = job_ids[step][0]
            break
    else:
        # No job found in canonical order, try any step
        for uuid_list in job_ids.values():
            if uuid_list:
                first_uuid = uuid_list[0]
                break
        else:
            return None

    try:
        manager = manager_getter()
        jc = manager._ensure_job_controller()
        job_info = jc.get_job_info(job_id=first_uuid)
        if job_info is None or not job_info.run_dir:
            return None
        return str(job_info.run_dir)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Worker details
# ---------------------------------------------------------------------------


def get_worker_details(
    manager_getter: Callable[[], MainWorkflow],
) -> list[dict]:
    """Return per-worker status, current user, and active job count.

    ``current_user`` is determined by aggregating
    ``job.metadata.qdyn_user`` from non-terminal jobs on each worker.
    """
    manager = manager_getter()
    pool_name = manager.active_pool_name
    pool_workers = manager._get_pool_workers(pool_name)

    result: list[dict] = []

    try:
        jc = manager._ensure_job_controller()

        # Aggregate: per worker, count active jobs and collect qdyn_user
        pipeline = [
            {
                "$match": {
                    "worker": {"$in": pool_workers},
                    "state": {"$nin": MainWorkflow._TERMINAL_STATES},
                }
            },
            {
                "$group": {
                    "_id": "$worker",
                    "active_jobs": {"$sum": 1},
                    "users": {"$addToSet": "$job.metadata.qdyn_user"},
                }
            },
        ]
        worker_stats: Dict[str, dict] = {}
        for doc in jc.jobs.aggregate(pipeline):
            users = [u for u in (doc.get("users") or []) if u]
            worker_stats[doc["_id"]] = {
                "active_jobs": doc["active_jobs"],
                "current_user": users[0] if len(users) == 1 else (
                    ", ".join(sorted(users)) if users else None
                ),
            }

        for worker_name in pool_workers:
            stats = worker_stats.get(worker_name)
            if stats:
                result.append(
                    {
                        "name": worker_name,
                        "status": "busy",
                        "current_user": stats["current_user"],
                        "active_jobs": stats["active_jobs"],
                    }
                )
            else:
                result.append(
                    {
                        "name": worker_name,
                        "status": "idle",
                        "current_user": None,
                        "active_jobs": 0,
                    }
                )
    except Exception as exc:
        logger.warning("Failed to query worker details: %s", exc)
        # Return all workers as unknown
        for worker_name in pool_workers:
            result.append(
                {
                    "name": worker_name,
                    "status": "idle",
                    "current_user": None,
                    "active_jobs": 0,
                }
            )

    return result


# ---------------------------------------------------------------------------
# Admin task operations (stop / continue / delete)
# ---------------------------------------------------------------------------


def admin_stop_task(
    task_id: str,
    manager_getter: Callable[[], MainWorkflow],
    admin_username: str,
) -> dict:
    """Stop all stoppable jobs for a task (admin action).

    Parameters
    ----------
    task_id : str
        The task to stop.
    manager_getter : callable
        Returns the MainWorkflow instance.
    admin_username : str
        The admin performing the action (for audit logging).

    Returns
    -------
    dict
        Result with keys ``stopped``, ``skipped``, ``failed``.

    Raises
    ------
    HTTPException
        404 if task not found.
    """
    # Verify task exists in DB
    owner = qdyndb.get_task_owner(task_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="Task not found")

    manager = manager_getter()

    # The task must be in the in-memory tracking for stop_task_jobs to work
    if task_id not in manager.task_ids:
        raise HTTPException(
            status_code=404,
            detail=f"Task '{task_id}' is not in the active workflow tracker",
        )

    result = manager.stop_task_jobs(task_id)
    qdyndb.log_audit(
        admin_username,
        "admin_stop_task",
        target=task_id,
        detail=f"owner={owner}",
    )
    logger.info(
        "Admin '%s' stopped task '%s' (owner: '%s'): "
        "%d stopped, %d skipped, %d failed",
        admin_username,
        task_id,
        owner,
        len(result["stopped"]),
        len(result["skipped"]),
        len(result["failed"]),
    )
    return result


def admin_continue_task(
    task_id: str,
    manager_getter: Callable[[], MainWorkflow],
    admin_username: str,
) -> dict:
    """Resume all paused/stopped jobs for a task (admin action).

    Parameters
    ----------
    task_id : str
        The task to continue.
    manager_getter : callable
        Returns the MainWorkflow instance.
    admin_username : str
        The admin performing the action (for audit logging).

    Returns
    -------
    dict
        Result with keys ``continued``, ``skipped``, ``failed``.

    Raises
    ------
    HTTPException
        404 if task not found.
    """
    owner = qdyndb.get_task_owner(task_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="Task not found")

    manager = manager_getter()

    if task_id not in manager.task_ids:
        raise HTTPException(
            status_code=404,
            detail=f"Task '{task_id}' is not in the active workflow tracker",
        )

    result = manager.continue_task_jobs(task_id)
    qdyndb.log_audit(
        admin_username,
        "admin_continue_task",
        target=task_id,
        detail=f"owner={owner}",
    )
    logger.info(
        "Admin '%s' continued task '%s' (owner: '%s'): "
        "%d continued, %d skipped, %d failed",
        admin_username,
        task_id,
        owner,
        len(result["continued"]),
        len(result["skipped"]),
        len(result["failed"]),
    )
    return result


def admin_delete_task(
    task_id: str,
    manager_getter: Callable[[], MainWorkflow],
    admin_username: str,
    cleanup_dirs: bool = True,
) -> None:
    """Delete a task record with optional work_dir cleanup (admin action).

    Steps:
    1. Verify task exists.
    2. Collect all job run_dirs (via jc.get_job_info).
    3. Call manager.delete_task_record() (stops jobs + deletes DB records).
    4. Delete queued_submissions entry if present.
    5. If cleanup_dirs, delete each run_dir with safety validation.

    Parameters
    ----------
    task_id : str
        The task to delete.
    manager_getter : callable
        Returns the MainWorkflow instance.
    admin_username : str
        The admin performing the action (for audit logging).
    cleanup_dirs : bool
        Whether to delete the job run directories on disk (default True).

    Raises
    ------
    HTTPException
        404 if task not found.
        500 if jobs could not be stopped (propagated from delete_task_record).
    """
    owner = qdyndb.get_task_owner(task_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="Task not found")

    manager = manager_getter()

    # Resolve work_dir_base for safety validation
    _, _, pool_cfg = manager._resolve_pool_context()
    work_dir_base = pool_cfg.get("work_dir_base", "")
    work_dir_base_resolved = (
        Path(work_dir_base).resolve() if work_dir_base else None
    )

    # Collect run_dirs before deletion (they become inaccessible after)
    run_dirs_to_delete: list[Path] = []
    if cleanup_dirs:
        job_ids = qdyndb.get_task_job_ids(task_id)
        if job_ids:
            try:
                jc = manager._ensure_job_controller()
                for uuid_list in job_ids.values():
                    for job_uuid in uuid_list:
                        try:
                            job_info = jc.get_job_info(job_id=job_uuid)
                            if job_info and job_info.run_dir:
                                rd = Path(str(job_info.run_dir)).resolve()
                                # Safety: run_dir must be under work_dir_base
                                if (
                                    work_dir_base_resolved
                                    and rd != work_dir_base_resolved
                                    and str(rd).startswith(
                                        str(work_dir_base_resolved) + "/"
                                    )
                                ):
                                    run_dirs_to_delete.append(rd)
                                else:
                                    logger.warning(
                                        "Skipping run_dir cleanup for '%s': "
                                        "path is outside work_dir_base '%s'",
                                        rd,
                                        work_dir_base_resolved,
                                    )
                        except Exception as exc:
                            logger.warning(
                                "Failed to get run_dir for job '%s': %s",
                                job_uuid,
                                exc,
                            )
            except Exception as exc:
                logger.warning(
                    "Failed to collect run_dirs for task '%s': %s",
                    task_id,
                    exc,
                )

    # Delete the task record (stops jobs + removes from DB + in-memory)
    if task_id in manager.task_ids:
        try:
            manager.delete_task_record(task_id)
        except RuntimeError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to delete task: {exc}",
            )
    else:
        # Task not in memory tracker, just delete DB record directly
        qdyndb.delete_task_record(task_id)

    # Also delete queued_submissions entry if present
    conn = qdyndb.get_db()
    with qdyndb._lock:
        conn.execute(
            "DELETE FROM queued_submissions WHERE task_id = ?",
            (task_id,),
        )
        conn.commit()

    # Clean up run directories on disk
    deleted_dirs = 0
    failed_dirs = 0
    if cleanup_dirs:
        for rd in run_dirs_to_delete:
            try:
                if rd.is_dir():
                    shutil.rmtree(rd)
                    deleted_dirs += 1
            except Exception as exc:
                failed_dirs += 1
                logger.warning(
                    "Failed to delete run_dir '%s': %s", rd, exc
                )

    qdyndb.log_audit(
        admin_username,
        "admin_delete_task",
        target=task_id,
        detail=f"owner={owner}, dirs_deleted={deleted_dirs}",
    )
    logger.info(
        "Admin '%s' deleted task '%s' (owner: '%s'): "
        "%d dirs deleted, %d dirs failed",
        admin_username,
        task_id,
        owner,
        deleted_dirs,
        failed_dirs,
    )


# ---------------------------------------------------------------------------
# File browser: list work_dir_base entries with task mapping
# ---------------------------------------------------------------------------


def _resolve_work_dir_base(
    manager_getter: Callable[[], MainWorkflow],
) -> tuple[str, Path | None]:
    """Return (work_dir_base_str, resolved_path | None)."""
    manager = manager_getter()
    _, _, pool_cfg = manager._resolve_pool_context()
    work_dir_base = pool_cfg.get("work_dir_base", "")
    if not work_dir_base or not os.path.isdir(work_dir_base):
        return work_dir_base, None
    return work_dir_base, Path(work_dir_base).resolve()


def _scan_file_summary(dir_path: str, prefix: str = "") -> list[dict]:
    """Recursively scan a directory and return file name+size list.

    Subdirectory files are prefixed with the relative path, e.g.
    ``scf_000/OUTCAR``, ``scf_001/WAVECAR``.
    """
    result: list[dict] = []
    try:
        with os.scandir(dir_path) as it:
            for entry in it:
                try:
                    name = f"{prefix}{entry.name}" if prefix else entry.name
                    if entry.is_file(follow_symlinks=False):
                        st = entry.stat(follow_symlinks=False)
                        result.append({"name": name, "size": st.st_size})
                    elif entry.is_dir(follow_symlinks=False):
                        result.extend(
                            _scan_file_summary(entry.path, prefix=f"{name}/")
                        )
                except OSError:
                    pass
    except OSError:
        pass
    result.sort(key=lambda f: f["name"])
    return result


def _build_uuid_to_task_map() -> dict[str, tuple[str, str]]:
    """Build reverse mapping: job_uuid -> (task_id, owner)."""
    uuid_to_task: dict[str, tuple[str, str]] = {}
    all_task_owners = qdyndb.get_all_task_owners()
    for row in all_task_owners:
        task_id = row["task_id"]
        owner = row["username"]
        job_ids_raw = row.get("job_ids", "{}")
        try:
            job_ids = (
                json.loads(job_ids_raw)
                if isinstance(job_ids_raw, str)
                else job_ids_raw
            )
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(job_ids, dict):
            for uuid_list in job_ids.values():
                if isinstance(uuid_list, list):
                    for uid in uuid_list:
                        uuid_to_task[uid] = (task_id, owner)
    return uuid_to_task


def list_work_dir_entries(
    manager_getter: Callable[[], MainWorkflow],
) -> dict:
    """Scan work_dir_base for job directories and map them to tasks.

    Results are cached for 5 minutes. Use invalidate_files_cache() to
    force a refresh (called after delete operations).
    """
    global _files_cache, _files_cache_time

    now = _time.monotonic()
    if _files_cache is not None and (now - _files_cache_time) < _FILES_CACHE_TTL:
        return _files_cache

    result = _list_work_dir_entries_uncached(manager_getter)
    _files_cache = result
    _files_cache_time = now
    return result


def _list_work_dir_entries_uncached(
    manager_getter: Callable[[], MainWorkflow],
) -> dict:
    """Actual scan logic (uncached)."""
    work_dir_base_str, base_resolved = _resolve_work_dir_base(manager_getter)
    if base_resolved is None:
        return {
            "work_dir_base": work_dir_base_str,
            "total_entries": 0,
            "orphan_count": 0,
            "entries": [],
        }

    uuid_to_task = _build_uuid_to_task_map()
    base = base_resolved

    entries: list[dict] = []
    try:
        for l1 in sorted(base.iterdir()):
            if not l1.is_dir() or len(l1.name) != 2:
                if l1.is_dir() and not l1.name.startswith("."):
                    _scan_bucket_tree(
                        l1, 0, 4, base, uuid_to_task, entries
                    )
                continue
            _scan_bucket_level(l1, 1, base, uuid_to_task, entries)
    except Exception as exc:
        logger.warning("Error scanning work_dir_base: %s", exc)

    return {
        "work_dir_base": str(base),
        "total_entries": len(entries),
        "orphan_count": sum(1 for e in entries if e["orphan"]),
        "entries": entries,
    }


def _scan_bucket_level(
    current: Path,
    depth: int,
    base: Path,
    uuid_to_task: dict[str, tuple[str, str]],
    entries: list[dict],
) -> None:
    """Recursively descend 2-char bucket directories until leaf."""
    try:
        for child in sorted(current.iterdir()):
            if not child.is_dir():
                continue
            if depth < 3 and len(child.name) == 2:
                _scan_bucket_level(
                    child, depth + 1, base, uuid_to_task, entries
                )
            else:
                _collect_leaf(child, base, uuid_to_task, entries)
    except OSError:
        pass


def _scan_bucket_tree(
    current: Path,
    depth: int,
    max_depth: int,
    base: Path,
    uuid_to_task: dict[str, tuple[str, str]],
    entries: list[dict],
) -> None:
    """Scan worker-prefixed layouts (e.g. worker_name/xx/xx/xx/uuid_idx)."""
    try:
        for child in sorted(current.iterdir()):
            if not child.is_dir():
                continue
            if depth + 1 < max_depth and len(child.name) == 2:
                _scan_bucket_tree(
                    child, depth + 1, max_depth, base, uuid_to_task, entries
                )
            elif depth + 1 >= max_depth:
                _collect_leaf(child, base, uuid_to_task, entries)
            else:
                # Non-2-char subdir at intermediate level -- keep searching
                _scan_bucket_tree(
                    child, depth + 1, max_depth, base, uuid_to_task, entries
                )
    except OSError:
        pass


def _collect_leaf(
    leaf: Path,
    base: Path,
    uuid_to_task: dict[str, tuple[str, str]],
    entries: list[dict],
) -> None:
    """Process a single leaf job directory and append to entries."""
    dir_name = leaf.name
    job_uuid = (
        dir_name.rsplit("_", 1)[0] if "_" in dir_name else dir_name
    )

    task_id = None
    owner = None
    if job_uuid in uuid_to_task:
        task_id, owner = uuid_to_task[job_uuid]

    # Try StorageCache first, then os.scandir aggregation
    size_bytes: int | None = None
    if _storage_cache is not None:
        size_bytes = _storage_cache.get_job_dir_size(str(leaf))

    # Scan files in the directory (single level)
    file_summary = _scan_file_summary(str(leaf))

    # If no cache hit, use du -sb (fast, consistent with dashboard)
    if size_bytes is None:
        import subprocess
        try:
            result = subprocess.run(
                ["du", "-sb", str(leaf)],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                size_bytes = int(result.stdout.split()[0])
        except Exception:
            # Last resort: sum from file_summary
            size_bytes = sum(f["size"] for f in file_summary)

    entries.append(
        {
            "path": str(leaf.relative_to(base)),
            "abs_path": str(leaf),
            "size_bytes": size_bytes,
            "job_uuid": job_uuid,
            "task_id": task_id,
            "owner": owner,
            "orphan": task_id is None,
            "file_summary": file_summary,
        }
    )


# ---------------------------------------------------------------------------
# File deletion helpers
# ---------------------------------------------------------------------------


def _validate_path_in_base(abs_path: str, base_resolved: Path) -> Path:
    """Validate that abs_path resolves to a location under base_resolved.

    Raises HTTPException 403 if the path escapes the base directory.
    """
    resolved = Path(abs_path).resolve()
    if resolved == base_resolved or not str(resolved).startswith(
        str(base_resolved) + "/"
    ):
        raise HTTPException(
            status_code=403,
            detail=f"Path '{abs_path}' is outside work_dir_base",
        )
    return resolved


def delete_files(
    targets: list[dict],
    delete_associated_tasks: bool,
    manager_getter: Callable[[], MainWorkflow],
) -> dict:
    """Bulk delete job directories or individual files.

    Parameters
    ----------
    targets : list[dict]
        Each dict has ``abs_path`` (str) and optional ``task_id`` (str | None).
    delete_associated_tasks : bool
        If True, also call admin_delete_task for targets with a task_id.
    manager_getter : callable
        Returns the MainWorkflow instance.

    Returns
    -------
    dict with ``deleted`` (int) and ``failed`` (list of {path, error}).
    """
    _, base_resolved = _resolve_work_dir_base(manager_getter)
    if base_resolved is None:
        raise HTTPException(
            status_code=500,
            detail="work_dir_base is not configured or does not exist",
        )

    deleted = 0
    failed: list[dict] = []

    # If delete_associated_tasks, handle task deletions first
    if delete_associated_tasks:
        seen_task_ids: set[str] = set()
        for target in targets:
            tid = target.get("task_id")
            if tid and tid not in seen_task_ids:
                seen_task_ids.add(tid)
                try:
                    admin_delete_task(
                        tid,
                        manager_getter,
                        admin_username="system",
                        cleanup_dirs=False,  # we handle dirs ourselves
                    )
                except HTTPException:
                    pass  # task may already be deleted
                except Exception as exc:
                    logger.warning(
                        "Failed to delete task '%s': %s", tid, exc
                    )

    for target in targets:
        abs_path = target["abs_path"]
        try:
            resolved = _validate_path_in_base(abs_path, base_resolved)
            if resolved.is_dir():
                shutil.rmtree(resolved)
                deleted += 1
            elif resolved.is_file():
                resolved.unlink()
                deleted += 1
            else:
                failed.append(
                    {"path": abs_path, "error": "Path does not exist"}
                )
        except HTTPException:
            failed.append(
                {"path": abs_path, "error": "Path outside work_dir_base"}
            )
        except Exception as exc:
            failed.append({"path": abs_path, "error": str(exc)})

    if deleted > 0:
        invalidate_files_cache()
        qdyndb.log_audit(
            "system",
            "admin_delete_files",
            detail=f"deleted={deleted}",
        )
    return {"deleted": deleted, "failed": failed}


def delete_files_by_name(
    filename: str,
    job_dirs: list[str],
    manager_getter: Callable[[], MainWorkflow],
) -> dict:
    """Delete a specific file from multiple job directories.

    Parameters
    ----------
    filename : str
        The filename to delete (e.g. "WAVECAR").
    job_dirs : list[str]
        Absolute paths of job directories to search.
    manager_getter : callable
        Returns the MainWorkflow instance.

    Returns
    -------
    dict with ``deleted`` (int) and ``failed`` (list of {path, error}).
    """
    _, base_resolved = _resolve_work_dir_base(manager_getter)
    if base_resolved is None:
        raise HTTPException(
            status_code=500,
            detail="work_dir_base is not configured or does not exist",
        )

    deleted = 0
    failed: list[dict] = []

    for job_dir in job_dirs:
        file_path = os.path.join(job_dir, filename)
        try:
            # Validate the job_dir is under work_dir_base
            _validate_path_in_base(job_dir, base_resolved)

            resolved_file = Path(file_path).resolve()
            if resolved_file.is_file():
                resolved_file.unlink()
                deleted += 1
            else:
                failed.append(
                    {"path": file_path, "error": "File does not exist"}
                )
        except HTTPException:
            failed.append(
                {"path": file_path, "error": "Path outside work_dir_base"}
            )
        except Exception as exc:
            failed.append({"path": file_path, "error": str(exc)})

    if deleted > 0:
        invalidate_files_cache()
        qdyndb.log_audit(
            "system",
            "admin_delete_files_by_name",
            detail=f"filename={filename}, deleted={deleted}",
        )

    return {"deleted": deleted, "failed": failed}


# ---------------------------------------------------------------------------
# Trajectory management
# ---------------------------------------------------------------------------

_HASH_RE = re.compile(r"^[0-9a-f]{32}$")


def _get_traj_dir(
    manager_getter: Callable[[], MainWorkflow],
) -> Path:
    """Resolve the trajectory storage directory from config."""
    manager = manager_getter()
    user_data_dir = str(
        Path(
            manager.config["basic"].get("user_data", "data/user_data")
        ).resolve()
    )
    return Path(user_data_dir) / "trajs"


def _count_traj_refs(file_hash: str) -> int:
    """Count how many distinct tasks reference a trajectory hash.

    Uses UNION to deduplicate across queued_submissions (queued tasks)
    and task_owners (directly submitted tasks).
    """
    conn = qdyndb.get_db()
    with qdyndb._lock:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM ("
            "  SELECT task_id FROM queued_submissions "
            "    WHERE payload_json LIKE ? "
            "  UNION "
            "  SELECT task_id FROM task_owners "
            "    WHERE stru_hash = ?"
            ")",
            (f"%{file_hash}%", file_hash),
        ).fetchone()
    return row["cnt"] if row else 0


def list_trajectories(
    manager_getter: Callable[[], MainWorkflow],
) -> dict:
    """List all trajectory files with metadata and reference counts.

    Returns a dict matching TrajListResponse fields.
    """
    traj_dir = _get_traj_dir(manager_getter)
    if not traj_dir.is_dir():
        return {"total": 0, "total_bytes": 0, "items": []}

    from ..params import md_ase_formats

    items: list[dict] = []
    total_bytes = 0

    try:
        for entry in os.scandir(str(traj_dir)):
            if not entry.is_file(follow_symlinks=False):
                continue
            if not _HASH_RE.match(entry.name):
                continue

            stat = entry.stat(follow_symlinks=False)
            size = stat.st_size
            total_bytes += size

            # Format creation time from mtime
            mtime = datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            )
            created_at = mtime.strftime("%Y-%m-%d %H:%M:%S")

            # Parse structure metadata with ASE
            fmt_name: str | None = None
            formula: str | None = None
            num_atoms: int | None = None
            num_frames: int | None = None

            for sw_fmt, ase_fmt in md_ase_formats.items():
                try:
                    import ase.io

                    atoms = ase.io.read(
                        entry.path, format=ase_fmt, index=0
                    )
                    formula = atoms.get_chemical_formula()
                    num_atoms = len(atoms)
                    fmt_name = ase_fmt
                    # Count frames using lightweight method
                    try:
                        from ..app import _count_trajectory_frames

                        num_frames = _count_trajectory_frames(
                            entry.path, ase_fmt
                        )
                    except Exception:
                        num_frames = None
                    break
                except Exception:
                    continue

            # Reference count
            ref_count = _count_traj_refs(entry.name)

            items.append(
                {
                    "hash": entry.name,
                    "size_bytes": size,
                    "created_at": created_at,
                    "format": fmt_name,
                    "formula": formula,
                    "num_atoms": num_atoms,
                    "num_frames": num_frames,
                    "ref_count": ref_count,
                }
            )
    except OSError as exc:
        logger.warning("Failed to scan trajectory directory: %s", exc)

    # Sort by creation time descending
    items.sort(key=lambda x: x["created_at"], reverse=True)

    return {
        "total": len(items),
        "total_bytes": total_bytes,
        "items": items,
    }


def delete_trajectory(
    file_hash: str,
    manager_getter: Callable[[], MainWorkflow],
    admin_username: str,
    force: bool = False,
) -> None:
    """Delete a trajectory file by its hash.

    Parameters
    ----------
    file_hash : str
        The 32-character hex hash of the trajectory file.
    manager_getter : callable
        Returns the MainWorkflow instance.
    admin_username : str
        The admin performing the deletion (for audit).
    force : bool
        If True, delete even if references exist.

    Raises
    ------
    HTTPException
        400 if hash format is invalid.
        404 if file not found.
        409 if file is referenced and force is False.
    """
    if not _HASH_RE.match(file_hash):
        raise HTTPException(
            status_code=400,
            detail="Invalid hash format: expected 32-char hex string",
        )

    traj_dir = _get_traj_dir(manager_getter)
    file_path = traj_dir / file_hash

    if not file_path.is_file():
        raise HTTPException(
            status_code=404, detail="Trajectory file not found"
        )

    if not force:
        ref_count = _count_traj_refs(file_hash)
        if ref_count > 0:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Trajectory '{file_hash}' is referenced by "
                    f"{ref_count} submission(s). Use force=true to "
                    f"delete anyway."
                ),
            )

    file_path.unlink()
    qdyndb.log_audit(
        admin_username,
        "admin_delete_trajectory",
        target=file_hash,
    )
    logger.info(
        "Admin '%s' deleted trajectory '%s'.",
        admin_username,
        file_hash,
    )


# ---------------------------------------------------------------------------
# Log viewer
# ---------------------------------------------------------------------------

# Base directory for log files, resolved relative to the package root.
# Layout: <project>/logs/backend.log, <project>/logs/frontend.log
_LOGS_BASE: Path | None = None


def _get_logs_base() -> Path:
    """Return the logs directory path, caching for performance."""
    global _LOGS_BASE
    if _LOGS_BASE is None:
        # src/qdyn/admin/service.py -> src/qdyn/admin -> src/qdyn -> src -> project root
        _LOGS_BASE = Path(__file__).resolve().parent.parent.parent.parent / "logs"
    return _LOGS_BASE


def read_log_tail(
    log_name: str = "backend",
    num_lines: int = 200,
) -> dict:
    """Read the last N lines of a log file.

    Parameters
    ----------
    log_name : str
        Log file to read: "backend" or "frontend".
    num_lines : int
        Number of lines to read from the end (default 200).

    Returns
    -------
    dict matching LogViewResponse fields.

    Raises
    ------
    HTTPException
        400 if log_name is invalid.
        404 if log file does not exist.
    """
    if log_name not in ("backend", "frontend"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid log name '{log_name}'. Must be 'backend' or 'frontend'.",
        )

    logs_dir = _get_logs_base()
    log_path = logs_dir / f"{log_name}.log"

    if not log_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Log file '{log_name}.log' not found",
        )

    file_size = log_path.stat().st_size

    # Use deque for efficient tail reading
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            tail = deque(f, maxlen=num_lines)
        lines = [line.rstrip("\n") for line in tail]
    except Exception as exc:
        logger.warning("Failed to read log file '%s': %s", log_path, exc)
        lines = []

    # Approximate total line count from file size
    # (more efficient than reading the entire file for large logs)
    avg_line_len = max(1, file_size // max(1, len(lines))) if lines else 80
    total_lines = file_size // avg_line_len if file_size > 0 else 0

    return {
        "log_name": log_name,
        "lines": lines,
        "total_lines": total_lines,
        "file_size": file_size,
    }
