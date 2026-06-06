import asyncio
import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, Literal

import ase
import ase.io
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi import status as http_status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from qdyn import __version__

from .auth import auth_router, get_current_user
from .auth.security import configure as configure_auth
from .calc_common import extract_structure_metadata
from .errors import ConfigError
from .database import qdyndb
from .frontend_api import create_frontend_router
from .input import InputT, NVTInputT, NVEInputT, SCFInputT, PreNAMDInputT, NAMDInputT
from .main_workflow import (
    MainWorkflow, ValidationError, ResumeError, QueryError,
)
from .pool import WorkerPool
from .params import HASH_PATTERN as _HASH_PATTERN
from .validation import validate_and_fill_runtime_config

# Maximum upload file size: 1 GB.
# Trajectory files are typically a few tens of MB; HamGNN checkpoints can be ~700 MB.
MAX_UPLOAD_SIZE = 1024 * 1024 * 1024

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

manager: MainWorkflow | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global manager
    config_path = (
        getattr(app.state, "config_path", None)
        or os.environ.get("QDYN_CONFIG")
        or "config/qdyn.yaml"
    )
    config_path = Path(config_path).expanduser().resolve()
    manager = MainWorkflow(config_path)
    validate_and_fill_runtime_config(
        manager.config,
        manager.jf_config,
    )
    manager.init_active_pool()

    auth_cfg = manager.config["auth"]

    # --- auth & DB init ---
    db_path = manager.config["basic"]["user_db_path"]
    qdyndb.init_db(db_path)

    secret_key = auth_cfg["secret_key"]
    expire_hours = auth_cfg["token_expire_hours"]
    generated_key = configure_auth(secret_key, expire_hours)

    # user_data folders are created on demand when uploading files, if not presented.
    # One user_data for each worker. No longer created at startup.

    # persist auto-generated key back to config file if it was empty
    if not auth_cfg["secret_key"]:
        manager.config["auth"]["secret_key"] = generated_key
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

    # Start the queue poller background task.
    from .queue_poller import queue_dispatch_loop

    # Read poll interval from normalized pool config.
    pool_cfg = manager.active_pool.pool_cfg
    poll_interval = pool_cfg["queue_poll_interval"]

    poller_task: asyncio.Task | None = asyncio.create_task(
        queue_dispatch_loop(
            workflow=manager,
            db=qdyndb,
            dispatch_lock=_dispatch_lock,
            interval=poll_interval,
        ),
        name="queue-poller",
    )
    logging.info(
        "Queue poller background task started (interval=%ds).",
        poll_interval,
    )

    yield

    # --- shutdown ---
    if poller_task is not None:
        poller_task.cancel()
        try:
            await poller_task
        except asyncio.CancelledError:
            pass
        logging.info("Queue poller background task stopped.")

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
# Step-input schema endpoint
# ---------------------------------------------------------------------------

def _prune_hidden_fields(schema: dict[str, Any]) -> dict[str, Any]:
    """Recursively remove properties marked with hidden: true from a JSON schema.

    Also cleans up ``required`` lists so the schema stays self-consistent.
    Processes top-level properties as well as nested ``$defs``.
    """
    schema = dict(schema)  # shallow copy

    def _prune_properties(obj: dict[str, Any]) -> dict[str, Any]:
        obj = dict(obj)
        props = obj.get("properties")
        if not isinstance(props, dict):
            return obj
        hidden_keys = [k for k, v in props.items() if isinstance(v, dict) and v.get("hidden")]
        if hidden_keys:
            props = {k: v for k, v in props.items() if k not in hidden_keys}
            obj["properties"] = props
            req = obj.get("required")
            if isinstance(req, list):
                obj["required"] = [r for r in req if r not in hidden_keys]
                if not obj["required"]:
                    del obj["required"]
        return obj

    # prune top-level properties
    schema = _prune_properties(schema)

    # prune inside $defs
    defs = schema.get("$defs")
    if isinstance(defs, dict):
        schema["$defs"] = {name: _prune_properties(defn) for name, defn in defs.items()}

    return schema


def build_step_input_schemas() -> dict[str, dict[str, Any]]:
    """Build JSON schemas for all step input models, with hidden fields removed."""
    raw = {
        "nvt": NVTInputT.model_json_schema(),
        "nve": NVEInputT.model_json_schema(),
        "scf": SCFInputT.model_json_schema(),
        "pre_namd": PreNAMDInputT.model_json_schema(),
        "namd": NAMDInputT.model_json_schema(),
    }
    return {key: _prune_hidden_fields(s) for key, s in raw.items()}


@app.get("/schema/step-inputs", tags=["schema"])
def get_step_input_schemas() -> dict[str, Any]:
    """Return JSON Schemas for all step input models (public, no auth)."""
    return build_step_input_schemas()


# ---------------------------------------------------------------------------
# Frontend API router
# ---------------------------------------------------------------------------

# Create and mount the frontend API router with manager injection
frontend_router = create_frontend_router(_manager)
app.include_router(frontend_router)


# ---------------------------------------------------------------------------
# Dispatch lock for pool-based submission
# ---------------------------------------------------------------------------
# Serialises "query MongoDB -> select worker -> submit_flow" so that two
# concurrent requests cannot both pick the same idle worker.
_dispatch_lock = asyncio.Lock()


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


def _sync_dispatch(
    m: MainWorkflow,
    task_id: str,
    username: str,
    pool_name: str,
    input_obj: InputT,
    method: str,
    resume: bool,
    prev_task_id: str,
    *,
    runtime_worker: str | None = None,
) -> str | None:
    """Synchronous core of the dispatch: select worker + submit + persist.

    Called inside ``asyncio.to_thread()`` while the dispatch lock is held.

    Parameters
    ----------
    runtime_worker : str, optional
        If provided, skip worker selection and submit directly to this
        worker (used by the queue poller when it has already determined
        the target worker).

    Returns the runtime worker name on success, or None if no worker is
    available (pool full).
    """
    if runtime_worker is None:
        worker, mode = m.active_pool.select_runtime_worker(username)
        if worker is None:
            return None
        runtime_worker = worker

    # Submit via jobflow-remote
    final_task_id, job_ids, active_worker = m.submit(
        input=input_obj,
        method=method,
        stru=input_obj.stru,
        stru_format=input_obj.stru_format,
        stru_hash=input_obj.stru_hash,
        resume=resume,
        prev_task_id=prev_task_id,
        task_id=task_id,
        username=username,
        runtime_worker=runtime_worker,
    )

    # Persist task ownership
    qdyndb.assign_task(final_task_id, username, job_ids, pool_name=pool_name)

    # Persist structure metadata
    formula, num_atoms = extract_structure_metadata(
        input_obj,
        resume,
        prev_task_id,
        pool=m.active_pool,
    )
    qdyndb.update_task_metadata(
        final_task_id,
        task_name=input_obj.task_name,
        formula=formula,
        num_atoms=num_atoms,
        prev_task_id=prev_task_id if resume and prev_task_id else None,
        worker=active_worker,
        pool_name=pool_name,
        stru_hash=input_obj.stru_hash,
        stru_format=input_obj.stru_format,
    )

    return runtime_worker


async def _dispatch_task(
    m: MainWorkflow,
    task_id: str,
    username: str,
    pool_name: str,
    input_obj: InputT,
    method: str,
    resume: bool,
    prev_task_id: str,
) -> str | None:
    """Acquire the dispatch lock, select a worker, and submit.

    Returns the runtime worker name on success, or None if all workers
    are occupied (caller should enqueue the task).
    """
    async with _dispatch_lock:
        return await asyncio.to_thread(
            _sync_dispatch,
            m, task_id, username, pool_name,
            input_obj, method, resume, prev_task_id,
        )


# --- endpoints ---


@app.get("/workers", tags=["system"])
def get_workers():
    """Return available pool names and the configured default."""
    m = _manager()
    workers = list(m.config["worker_pools"].keys())
    return {
        "workers": workers,
        "default": m.active_pool.name,
    }


class SubmitResponse(BaseModel):
    """Structured response from the /submit endpoint."""
    task_id: str
    status: Literal["SUBMITTED", "QUEUED"]
    worker: str | None = None
    queue_position: int | None = None


@app.post("/submit", response_model=SubmitResponse, status_code=201)
async def submit_task(
    input: InputT,
    method: Literal["namd", "n2amd"] = "namd",
    resume: bool = False,
    prev_task_id: str = "",
    username: str = Depends(get_current_user),
):
    """Submit a new task.

    The system automatically selects an idle worker from the active pool.
    If all workers are occupied, the task enters a FIFO waiting queue
    and will be dispatched by the background poller when a worker becomes
    available.

    Returns a structured response with the task ID, submission status
    (SUBMITTED or QUEUED), the assigned worker (if submitted), and the
    queue position (if queued).
    """
    m = _manager()

    # Ownership check for resume
    if resume and prev_task_id:
        prev_owner = qdyndb.get_task_owner(prev_task_id)
        if prev_owner is None:
            raise HTTPException(status_code=404, detail="Previous task not found")
        if prev_owner != username:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Cannot resume a task owned by another user",
            )

    from jobflow.utils import suid
    task_id = suid()
    pool_name = m.active_pool.name

    try:
        runtime_worker = await _dispatch_task(
            m, task_id, username, pool_name,
            input, method, resume, prev_task_id,
        )
    except (AssertionError, ValidationError) as e:
        raise HTTPException(status_code=422, detail=f"Validation error: {e}")
    except ConfigError as e:
        raise HTTPException(status_code=500, detail=f"Server config error: {e}")
    except ResumeError as e:
        raise HTTPException(status_code=404, detail=f"Resume error: {e}")
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=f"Not supported: {e}")

    if runtime_worker is not None:
        return SubmitResponse(
            task_id=task_id,
            status="SUBMITTED",
            worker=runtime_worker,
        )

    # No worker available: enqueue the task.
    payload = {
        "input": input.model_dump() if hasattr(input, "model_dump") else input.dict(),
        "method": method,
        "resume": resume,
        "prev_task_id": prev_task_id,
        "pool_name": pool_name,
    }
    qdyndb.enqueue_submission(task_id, username, pool_name, json.dumps(payload))

    # Also create a placeholder in task_owners so the task shows up in
    # the user's task list immediately (with empty job_ids).
    qdyndb.assign_task(task_id, username, {}, pool_name=pool_name)

    # Compute the queue position (1-based)
    all_queued = qdyndb.list_all_queued()
    position = next(
        (i + 1 for i, q in enumerate(all_queued) if q["task_id"] == task_id),
        len(all_queued),
    )

    # Extract and persist structure metadata even for queued tasks
    formula, num_atoms = extract_structure_metadata(
        input,
        resume,
        prev_task_id,
        m.active_pool,
    )
    qdyndb.update_task_metadata(
        task_id,
        task_name=input.task_name,
        formula=formula,
        num_atoms=num_atoms,
        prev_task_id=prev_task_id if resume and prev_task_id else None,
        worker=None,
        pool_name=pool_name,
        stru_hash=input.stru_hash,
        stru_format=input.stru_format,
    )

    return SubmitResponse(
        task_id=task_id,
        status="QUEUED",
        queue_position=position,
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


@app.post("/upload")
async def upload(
    file: UploadFile = File(...),
    file_type: Literal["trajectory", "model"] = Form(...),
    user: str = Depends(get_current_user),
):
    m = _manager()
    pool = m.active_pool

    target_dir = Path(pool.get_user_file_path(file_type))
    if not pool.remote:
        target_dir.mkdir(parents=True, exist_ok=True)

    # Stream read: compute MD5 while writing to temp file, enforcing size limit
    md5 = hashlib.md5()
    total_size = 0
    fd, tmp_path = tempfile.mkstemp(
        dir=None if pool.remote else str(target_dir),
        suffix='.tmp',
    )
    file_hash = ""
    try:
        with os.fdopen(fd, 'wb') as tmp_f:
            while chunk := await file.read(8 * 1024 * 1024):  # 8 MiB chunks
                total_size += len(chunk)
                if total_size > MAX_UPLOAD_SIZE:
                    os.unlink(tmp_path)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large (max {MAX_UPLOAD_SIZE // (1024 * 1024)} MB)",
                    )
                md5.update(chunk)
                tmp_f.write(chunk)
        file_hash = md5.hexdigest()
    except HTTPException:
        raise  # re-raise size limit error as-is
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    # For trajectory files, validate format and extract summary.
    # If the file cannot be parsed as any supported trajectory format,
    # delete it and return an error — don't keep garbage files on disk.
    summary = {}
    if file_type == "trajectory":
        from .calc_common import count_trajectory_frames
        from .params import TRAJ_FORMAT_MAPPING
        parsed = False
        for fmt in TRAJ_FORMAT_MAPPING.values():
            try:
                atoms = ase.io.read(str(tmp_path), format=fmt, index=0)
                summary = {
                    "formula": atoms.get_chemical_formula(),
                    "num_atoms": len(atoms),
                    "num_frames": count_trajectory_frames(
                        str(tmp_path), fmt
                    ),
                }
                parsed = True
                break
            except Exception:
                continue
        if not parsed:
            # Unrecognizable file — clean up and reject
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            tried = ', '.join(f'{k} ({v})' for k, v in TRAJ_FORMAT_MAPPING.items())
            raise HTTPException(
                status_code=422,
                detail=f"File is not a valid trajectory. "
                       f"Tried parsing as: {tried}. "
                       f"Please upload a trajectory file (e.g. XDATCAR for VASP).",
            )

    # upload tmp file to final_path on local/remote worker
    try:
        pool.upload_user_file(
            file_type=file_type, 
            file_hash=file_hash, 
            local_path=tmp_path
        )
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return {"hash": file_hash, "pool_name": pool.name, **summary}


@app.get("/upload/hash")
def check_hash(
    hash: str,
    file_type: Literal["trajectory", "model"],
    user: str = Depends(get_current_user),
):
    # Validate hash format to prevent path traversal
    if not _HASH_PATTERN.match(hash):
        raise HTTPException(status_code=422, 
                            detail="Invalid hash format: expected 32-char hex string")

    m = _manager()
    pool = m.active_pool
    exists = pool.user_file_exists(file_type, hash)

    # If file exists and is a trajectory, validate format and return summary.
    # If the file is invalid (e.g. leftover from before validation was added),
    # delete it and report as not existing — forces a clean re-upload.
    summary = {}
    if exists and file_type == "trajectory":
        from .calc_common import count_trajectory_frames, read_trajectory_summary
        from .params import TRAJ_FORMAT_MAPPING

        parsed, summary = read_trajectory_summary(
            pool=pool,
            file_hash=hash,
            formats=list(TRAJ_FORMAT_MAPPING.values()),
        )

        if not parsed:
            # Stale invalid file — clean up
            pool.delete_user_file(file_type=file_type, file_hash=hash)
            exists = False

    return {"exists": exists, "pool_name": pool.name, **summary}


# ---------------------------------------------------------------------------
# Pool status & queue management endpoints
# ---------------------------------------------------------------------------

class PoolStatusResponse(BaseModel):
    """Response model for ``GET /pool/status``."""
    pool_name: str
    total_workers: int
    idle_workers: int
    busy_workers: int
    user_occupied_workers: int


@app.get("/pool/status", response_model=PoolStatusResponse, tags=["pool"])
def get_pool_status(username: str = Depends(get_current_user)):
    """Return pool utilisation summary for the active pool.

    Shows total, idle, and busy worker counts, as well as how many
    workers the current user occupies vs. the per-user limit.
    """
    m = _manager()
    pool_name = m.active_pool.name
    pool_workers = m.active_pool.get_pool_workers()

    # Query MongoDB for busy workers (any non-terminal job)
    jc = m._ensure_job_controller()
    busy_pipeline = [
        {
            "$match": {
                "worker": {"$in": pool_workers},
                "state": {"$nin": WorkerPool._TERMINAL_STATES},
            }
        },
        {"$group": {"_id": "$worker"}},
    ]
    busy_workers = {doc["_id"] for doc in jc.jobs.aggregate(busy_pipeline)}

    user_workers = m.active_pool.get_user_occupied_workers(username)

    return PoolStatusResponse(
        pool_name=pool_name,
        total_workers=len(pool_workers),
        idle_workers=len(pool_workers) - len(busy_workers),
        busy_workers=len(busy_workers),
        user_occupied_workers=len(user_workers),
    )


@app.delete("/queue/{task_id}", tags=["pool"])
def cancel_queued_task(
    task_id: str,
    username: str = Depends(get_current_user),
):
    """Cancel a task that is currently in the waiting queue.

    Only tasks in QUEUED status can be cancelled.  The requesting user
    must own the task.  Returns the cancelled task_id on success, or
    raises 404/403 on failure.
    """
    success = qdyndb.cancel_queued(task_id, username)
    if not success:
        # Determine the specific error reason
        all_queued = qdyndb.list_queued_for_user(username)
        task_in_queue = any(q["task_id"] == task_id for q in all_queued)
        if not task_in_queue:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Task '{task_id}' not found in the queue for user "
                    f"'{username}'.  It may have already been dispatched "
                    f"or does not exist."
                ),
            )
        # Task exists but is not in QUEUED status (e.g. DISPATCHING)
        raise HTTPException(
            status_code=409,
            detail=(
                f"Task '{task_id}' is no longer in QUEUED status and "
                f"cannot be cancelled."
            ),
        )
    return {"task_id": task_id, "status": "CANCELLED"}


@app.get("/queue", tags=["pool"])
def list_user_queue(username: str = Depends(get_current_user)):
    """List the current user's queued submissions."""
    return qdyndb.list_queued_for_user(username)
