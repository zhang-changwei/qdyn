import logging
import os
from contextlib import asynccontextmanager
from typing import Literal, Optional

import yaml
from fastapi import Depends, FastAPI, HTTPException
from fastapi import status as http_status

from .auth import auth_router, get_current_user
from .auth.security import configure as configure_auth
from .database import qdyndb
from .input import InputT
from .main_workflow import MainWorkflow, ValidationError, ConfigError, ResumeError

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

manager: Optional[MainWorkflow] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global manager
    config_path = (
        getattr(app.state, "config_path", None)
        or os.environ.get("QDYN_CONFIG")
        or "config/qdyn.yaml"
    )
    manager = MainWorkflow(config_path)

    auth_cfg = manager.config.get("auth", {})

    # --- auth & DB init ---
    db_path = manager.config['basic'].get("user_db_path", "data/qdyn_users.db")
    qdyndb.init_db(db_path)

    secret_key = auth_cfg.get("secret_key", "")
    expire_hours = auth_cfg.get("token_expire_hours", 24)
    generated_key = configure_auth(secret_key, expire_hours)

    # persist auto-generated key back to config file if it was empty
    if not auth_cfg.get("secret_key"):
        manager.config.setdefault("auth", {})["secret_key"] = generated_key
        with open(config_path, "r") as f:
            raw = f.read()
            raw = raw.replace('secret_key: ""', f'secret_key: "{generated_key}"')
            raw = raw.replace("secret_key: ''", f'secret_key: "{generated_key}"')
        with open(config_path, "w") as f:
            f.write(raw)
        logging.info("Auto-generated auth secret_key and saved to config.")

    # restore task_ids and job_ids from DB
    restored = manager.restore_from_db(qdyndb.get_db())
    logging.info(f"Restored {restored} tasks from database.")

    yield

    # cleanup
    qdyndb.close_db()


app = FastAPI(title="QDYN Job Manager", lifespan=lifespan)
app.include_router(auth_router)


def _manager() -> MainWorkflow:
    if manager is None:
        raise RuntimeError("MainWorkflow not initialized yet.")
    return manager


# --- helpers ---


def _verify_ownership(task_id: str, username: str) -> None:
    """Raise 403 if the task does not belong to the user, 404 if not found."""
    m = _manager()

    owner = qdyndb.get_task_owner(task_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if owner != username:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )


def _submit_with_tracking(
    input: InputT,
    method: Literal["namd", "n2amd"],
    resume: bool,
    prev_task_id: str,
    username: str,
) -> str:
    """Submit a task and persist task ownership metadata."""
    m = _manager()
    try:
        task_id, job_ids = m.submit(
            input=input,
            method=method,
            stru=input.stru,
            stru_format=input.stru_format,
            resume=resume,
            prev_task_id=prev_task_id,
        )
    except (AssertionError, ValidationError) as e:
        raise HTTPException(status_code=422, detail=f"Validation error: {e}")
    except ConfigError as e:
        raise HTTPException(status_code=500, detail=f"Server config error: {e}")
    except ResumeError as e:
        raise HTTPException(status_code=404, detail=f"Resume error: {e}")

    qdyndb.assign_task(task_id, username, job_ids)
    return task_id


# --- endpoints ---


@app.post("/submit", response_model=str, status_code=201)
def submit_task(
    input: InputT,
    method: Literal["namd", "n2amd"] = "namd",
    resume: bool = False,
    prev_task_id: str = "",
    username: str = Depends(get_current_user),
):
    """Submit a new task and return its task ID."""
    return _submit_with_tracking(
        input=input,
        method=method,
        resume=resume,
        prev_task_id=prev_task_id,
        username=username,
    )


@app.get("/tasks", response_model=list[str])
def list_tasks(username: str = Depends(get_current_user)):
    """List all task IDs belonging to the current user."""
    return qdyndb.get_user_tasks(username)


@app.get("/tasks/{task_id}/jobs")
def list_task_jobs(task_id: str, username: str = Depends(get_current_user)):
    """List jobs (grouped by step) for a given task."""
    _verify_ownership(task_id, username)
    m = _manager()
    return m.list_task_jobs(task_id)


@app.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: str, username: str = Depends(get_current_user)):
    """Delete a task record."""
    pass
    # TODO


@app.get("/tasks/{task_id}/jobs/{job_uuid}/output")
def get_job_output(
    task_id: str,
    job_uuid: str,
    username: str = Depends(get_current_user),
):
    """Get the output of a specific job."""
    _verify_ownership(task_id, username)
    m = _manager()

    job_ids = m.list_task_jobs(task_id)
    jobs_flatten = []
    for job_list in job_ids.values():
        jobs_flatten.extend(job_list)
    if job_uuid not in jobs_flatten:
        raise HTTPException(status_code=404, detail="Job not found in this task")

    output = m.get_job_output(job_uuid)

    return output
