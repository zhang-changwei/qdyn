import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Literal, Optional

import yaml
from fastapi import Depends, FastAPI, HTTPException
from fastapi import status as http_status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from qdyn import __version__

from .auth import auth_router, get_current_user
from .auth.security import configure as configure_auth
from .database import qdyndb
from .frontend_api import create_frontend_router
from .input import InputT
from .main_workflow import MainWorkflow, ValidationError, ConfigError, ResumeError, QueryError

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

    # Pre-warm MongoDB connection at startup so the first request is fast
    try:
        manager._ensure_job_controller()
        logging.info("MongoDB connection pre-warmed successfully.")
    except Exception as exc:
        logging.warning(f"Failed to pre-warm MongoDB connection: {exc}")

    yield

    # cleanup
    qdyndb.close_db()


# ---------------------------------------------------------------------------
# Manager accessor function (must be defined before frontend router creation)
# ---------------------------------------------------------------------------

def _manager() -> MainWorkflow:
    """Get the MainWorkflow instance, raising RuntimeError if not initialized."""
    if manager is None:
        raise RuntimeError("MainWorkflow not initialized yet.")
    return manager


app = FastAPI(title="QDYN Job Manager", lifespan=lifespan)

# ---------------------------------------------------------------------------
# CORS middleware for frontend communication
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)


# ---------------------------------------------------------------------------
# Health check endpoint
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    """Health check response model."""
    status: str  # "ok" | "degraded"
    version: str
    timestamp: float


@app.get("/healthz", response_model=HealthResponse, tags=["system"])
async def health_check() -> HealthResponse:
    """
    Health check endpoint for monitoring and load balancers.

    Returns the current service status, version, and timestamp.
    """
    return HealthResponse(
        status="ok",
        version=__version__,
        timestamp=time.time(),
    )


# ---------------------------------------------------------------------------
# Frontend API router
# ---------------------------------------------------------------------------

# Create and mount the frontend API router with manager injection
frontend_router = create_frontend_router(_manager)
app.include_router(frontend_router)


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
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=f"Not supported: {e}")

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
    try:
        ids = m.list_task_jobs(task_id)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=f"Validation error: {e}")
    return ids


@app.get("/tasks/{task_id}/jobs/{job_uuid}/output")
def get_job_output(
    task_id: str,
    job_uuid: str,
    username: str = Depends(get_current_user),
):
    """Get the output of a specific job."""
    _verify_ownership(task_id, username)
    m = _manager()

    try:
        job_ids = m.list_task_jobs(task_id)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=f"Validation error: {e}")
    jobs_flatten = []
    for job_list in job_ids.values():
        jobs_flatten.extend(job_list)
    if job_uuid not in jobs_flatten:
        raise HTTPException(status_code=404, detail="Job not found in this task")

    try:
        output = m.get_job_output(job_uuid)
    except ConfigError as e:
        raise HTTPException(status_code=500, detail=f"Server config error: {e}")
    except QueryError as e:
        raise HTTPException(status_code=404, detail=f"Jobflow-remote query error: {e}")

    return output
