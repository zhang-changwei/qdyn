import logging
import os
from contextlib import asynccontextmanager
from typing import Literal, Optional

import yaml
from fastapi import Depends, FastAPI, HTTPException
from fastapi import status as http_status

from .auth import (
    auth_router,
    get_current_user,
    set_single_user_mode,
    init_db,
    get_db,
    assign_task,
    get_user_tasks,
    get_task_owner,
    get_task_job_ids,
    delete_task_record,
)
from .auth.security import configure as configure_auth
from .input import InputT
from .main_workflow import MainWorkflow, ValidationError, ConfigError, ResumeError

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

manager: Optional[MainWorkflow] = None
_single_user: bool = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    global manager, _single_user
    config_path = (
        app.state.config_path if hasattr(app.state, "config_path") else None
    )
    manager = MainWorkflow(config_path)

    auth_cfg = manager.config.get("auth", {})
    _single_user = auth_cfg.get("single_user_mode", False)
    set_single_user_mode(_single_user)

    if _single_user:
        logging.info("Running in single-user mode (no auth, no DB persistence).")
    else:
        # --- multi-user: auth & DB init ---
        db_path = auth_cfg.get("user_db_path", "data/qdyn_users.db")
        conn = init_db(db_path)

        secret_key = auth_cfg.get("secret_key", "")
        expire_hours = auth_cfg.get("token_expire_hours", 24)
        generated_key = configure_auth(secret_key, expire_hours)

        # persist auto-generated key back to config file if it was empty
        if not auth_cfg.get("secret_key"):
            manager.config.setdefault("auth", {})["secret_key"] = generated_key
            cfg_path = (
                config_path
                or os.environ.get("QDYN_CONFIG")
                or "config/qdyn.yaml"
            )
            cfg_path = os.path.abspath(cfg_path)
            with open(cfg_path, "r") as f:
                raw = yaml.safe_load(f) or {}
            raw.setdefault("auth", {})["secret_key"] = generated_key
            with open(cfg_path, "w") as f:
                yaml.dump(raw, f, default_flow_style=False)
            logging.info("Auto-generated auth secret_key and saved to config.")

        # restore task_ids and job_ids from DB
        restored = manager.restore_from_db(conn)
        logging.info(f"Restored {restored} tasks from database.")

    yield


app = FastAPI(title="QDYN Job Manager", lifespan=lifespan)
app.include_router(auth_router)


def _manager() -> MainWorkflow:
    if manager is None:
        raise RuntimeError("MainWorkflow not initialized yet.")
    return manager


# --- helpers ---


def _verify_ownership(task_id: str, username: str) -> None:
    """Raise 403 if the task does not belong to the user, 404 if not found.
    In single-user mode only checks existence (no ownership check)."""
    m = _manager()
    if _single_user:
        if task_id not in m.job_ids:
            raise HTTPException(status_code=404, detail="Task not found")
        return
    conn = get_db()
    owner = get_task_owner(conn, task_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if owner != username:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )


# --- endpoints ---


@app.post("/submit", response_model=str, status_code=201)
def submit_task(
    input: InputT,
    method: Literal["namd", "n2amd"] = "namd",
    stru: Optional[str] = "",
    stru_format: str = "vasp",
    resume: bool = False,
    prev_task_id: str = "",
    username: str = Depends(get_current_user),
):
    """Submit a new task and return its task ID."""
    m = _manager()
    try:
        task_id = m.submit(
            input=input,
            method=method,
            stru=stru,
            stru_format=stru_format,
            resume=resume,
            prev_task_id=prev_task_id,
        )
    except (AssertionError, ValidationError) as e:
        raise HTTPException(status_code=422, detail=f"Validation error: {e}")
    except ConfigError as e:
        raise HTTPException(status_code=500, detail=f"Server config error: {e}")
    except ResumeError as e:
        raise HTTPException(status_code=404, detail=f"Resume error: {e}")
    if not _single_user:
        conn = get_db()
        assign_task(conn, task_id, username, m.job_ids[task_id])
    return task_id


@app.get("/tasks", response_model=list[str])
def list_tasks(username: str = Depends(get_current_user)):
    """List all task IDs belonging to the current user."""
    if _single_user:
        return _manager().list_tasks()
    conn = get_db()
    return get_user_tasks(conn, username)


@app.get("/tasks/{task_id}/jobs")
def list_task_jobs(task_id: str, username: str = Depends(get_current_user)):
    """List jobs (grouped by step) for a given task."""
    _verify_ownership(task_id, username)
    if _single_user:
        return _manager().list_jobs(task_id)
    conn = get_db()
    return get_task_job_ids(conn, task_id)


@app.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: str, username: str = Depends(get_current_user)):
    """Delete a task record."""
    _verify_ownership(task_id, username)
    m = _manager()
    if not _single_user:
        conn = get_db()
        delete_task_record(conn, task_id)
    if task_id in m.task_ids:
        m.task_ids.remove(task_id)
    m.job_ids.pop(task_id, None)


@app.get("/tasks/{task_id}/jobs/{job_uuid}/output")
def get_job_output(
    task_id: str,
    job_uuid: str,
    username: str = Depends(get_current_user),
):
    """Get the output of a specific job."""
    _verify_ownership(task_id, username)
    m = _manager()
    if _single_user:
        job_ids = m.list_jobs(task_id)
    else:
        conn = get_db()
        job_ids = get_task_job_ids(conn, task_id)
    all_uuids = [u for uuids in job_ids.values() for u in uuids]
    if job_uuid not in all_uuids:
        raise HTTPException(status_code=404, detail="Job not found in this task")
    output = m.get_job_output(job_uuid)
    if output is None:
        raise HTTPException(status_code=404, detail="Job output not available")
    return output
