import hashlib
import logging
import os
import tempfile
from pathlib import Path
import time
from contextlib import asynccontextmanager
from typing import Any, Literal, Optional

import ase
import ase.io
import yaml
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi import status as http_status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from qdyn import __version__

from .auth import auth_router, get_current_user
from .auth.security import configure as configure_auth
from .database import qdyndb
from .frontend_api import create_frontend_router
from .input import InputT, NVTInputT, NVEInputT, SCFInputT, PreNAMDInputT, NAMDInputT
from .main_workflow import (
    MainWorkflow, ValidationError, ConfigError, ResumeError, QueryError,
)
from .params import HASH_PATTERN as _HASH_PATTERN

# Maximum upload file size: 500 MB.
# Trajectory files are typically a few tens of MB; 500 MB provides ample headroom.
MAX_UPLOAD_SIZE = 500 * 1024 * 1024

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

    # -- create user_data folder if not exist --
    user_data_dir = str(Path(manager.config['basic'].get('user_data', 'data/user_data')).resolve())
    traj_dir = os.path.join(user_data_dir, "trajs")
    model_dir = os.path.join(user_data_dir, "models")
    os.makedirs(traj_dir, exist_ok=True)
    os.makedirs(model_dir, exist_ok=True)

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
    worker: Optional[str] = None,
) -> str:
    """Submit a task and persist task ownership and structure metadata."""
    m = _manager()

    # Ownership check for resume: prev_task_id must belong to the same user
    if resume and prev_task_id:
        prev_owner = qdyndb.get_task_owner(prev_task_id)
        if prev_owner is None:
            raise HTTPException(status_code=404, detail="Previous task not found")
        if prev_owner != username:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Cannot resume a task owned by another user",
            )

    try:
        task_id, job_ids, effective_worker = m.submit(
            input=input,
            method=method,
            stru=input.stru,
            stru_format=input.stru_format,
            stru_hash=input.stru_hash,
            resume=resume,
            prev_task_id=prev_task_id,
            worker=worker,
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

    # Persist structure metadata for task summary / resume UI
    formula = None
    num_atoms = None
    if resume and prev_task_id:
        # Inherit metadata from the predecessor task
        prev_meta = qdyndb.get_task_metadata(prev_task_id)
        if prev_meta:
            formula = prev_meta.get("formula")
            num_atoms = prev_meta.get("num_atoms")
    else:
        # Parse from the uploaded POSCAR content
        if input.stru:
            try:
                import io
                from ase.io import read as ase_read
                atoms = ase_read(io.StringIO(input.stru), format=input.stru_format or "vasp")
                formula = atoms.get_chemical_formula()
                num_atoms = len(atoms)
            except Exception:
                logging.warning("Failed to parse structure metadata from POSCAR")
        elif input.stru_hash:
            # Hash format already validated by InputT.validate_stru_hash (pydantic)
            # Parse metadata from the trajectory file referenced by hash
            data_dir = str(Path(m.config['basic'].get('user_data', 'data/user_data')).resolve())
            traj_path = Path(data_dir) / "trajs" / input.stru_hash
            if traj_path.is_file():
                try:
                    from .params import md_ase_formats
                    ase_fmt = md_ase_formats.get(
                        input.stru_format, input.stru_format
                    )
                    atoms = ase.io.read(str(traj_path), format=ase_fmt, index=0)
                    formula = atoms.get_chemical_formula()
                    num_atoms = len(atoms)
                except Exception:
                    logging.warning(
                        "Failed to parse structure metadata from trajectory hash %s",
                        input.stru_hash,
                    )

    qdyndb.update_task_metadata(
        task_id,
        formula=formula,
        num_atoms=num_atoms,
        prev_task_id=prev_task_id if resume and prev_task_id else None,
        worker=effective_worker,
    )

    return task_id


# --- endpoints ---


@app.get("/workers", tags=["system"])
def get_workers():
    """Return available worker names and the configured default."""
    m = _manager()
    if "workers" in m.config:
        workers = list(m.config["workers"].keys())
    else:
        # Legacy config format: only one implicit worker
        workers = [m.worker_name]
    return {
        "workers": workers,
        "default": m.worker_name,
    }


@app.post("/submit", response_model=str, status_code=201)
def submit_task(
    input: InputT,
    method: Literal["namd", "n2amd"] = "namd",
    resume: bool = False,
    prev_task_id: str = "",
    worker: Optional[str] = None,
    username: str = Depends(get_current_user),
):
    """Submit a new task and return its task ID."""
    return _submit_with_tracking(
        input=input,
        method=method,
        resume=resume,
        prev_task_id=prev_task_id,
        username=username,
        worker=worker,
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


def _count_trajectory_frames(path: str, ase_format: str) -> int:
    """Count frames in a trajectory file without loading all atoms into memory.

    Uses format-specific lightweight scanning when available, falls back
    to ASE iread for unknown formats.

    Parameters
    ----------
    path : str
        Path to the trajectory file.
    ase_format : str
        ASE I/O format string (e.g. 'vasp-xdatcar').
    """
    if ase_format == "vasp-xdatcar":
        # Scan for "Direct configuration=" markers — O(n) read, no Atoms created
        with open(path, "r", encoding="utf-8", errors="replace") as fd:
            count = sum(1 for line in fd if "Direct configuration=" in line)
        # If no markers found but file is readable (e.g. single-frame POSCAR),
        # fall back to ASE to determine actual frame count
        if count > 0:
            return count

    # Generic fallback: may or may not be truly streaming depending on format.
    # TODO: add lightweight frame counters for other formats (e.g. xyz, cp2k)
    #       as they are supported, similar to the XDATCAR fast path above.
    from ase.io import iread
    return sum(1 for _ in iread(path, format=ase_format, index=":"))


@app.post("/upload")
async def upload(
    file: UploadFile = File(...),
    file_type: Literal["trajectory", "model"] = Form(...),
    user: str = Depends(get_current_user),
):
    m = _manager()
    type_mapping = {"trajectory": "trajs", "model": "models"}

    data_dir = str(Path(m.config['basic'].get('user_data', 'data/user_data')).resolve())
    target_dir = Path(data_dir) / type_mapping[file_type]
    target_dir.mkdir(parents=True, exist_ok=True)

    # Stream read: compute MD5 while writing to temp file, enforcing size limit
    md5 = hashlib.md5()
    total_size = 0
    fd, tmp_path = tempfile.mkstemp(dir=str(target_dir), suffix='.tmp')
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
        final_path = target_dir / file_hash
        if final_path.exists():
            os.unlink(tmp_path)  # dedup: already have it
        else:
            os.replace(tmp_path, final_path)  # atomic rename
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
        from .params import md_ase_formats
        parsed = False
        for fmt in md_ase_formats.values():
            try:
                atoms = ase.io.read(str(final_path), format=fmt, index=0)
                summary = {
                    "formula": atoms.get_chemical_formula(),
                    "num_atoms": len(atoms),
                    "num_frames": _count_trajectory_frames(
                        str(final_path), fmt
                    ),
                }
                parsed = True
                break
            except Exception:
                continue
        if not parsed:
            # Unrecognizable file — clean up and reject
            final_path.unlink(missing_ok=True)
            tried = ', '.join(f'{k} ({v})' for k, v in md_ase_formats.items())
            raise HTTPException(
                status_code=422,
                detail=f"File is not a valid trajectory. "
                       f"Tried parsing as: {tried}. "
                       f"Please upload a trajectory file (e.g. XDATCAR for VASP).",
            )

    return {"hash": file_hash, **summary}


@app.get("/upload/hash")
def check_hash(
    hash: str,
    file_type: Literal["trajectory", "model"],
    user: str = Depends(get_current_user),
):
    # Validate hash format to prevent path traversal
    if not _HASH_PATTERN.match(hash):
        raise HTTPException(status_code=422, detail="Invalid hash format: expected 32-char hex string")

    m = _manager()
    type_mapping = {"trajectory": "trajs", "model": "models"}

    data_dir = str(Path(m.config['basic'].get('user_data', 'data/user_data')).resolve())
    target_dir = Path(data_dir) / type_mapping[file_type]

    file_path = target_dir / hash
    exists = file_path.is_file()

    # If file exists and is a trajectory, validate format and return summary.
    # If the file is invalid (e.g. leftover from before validation was added),
    # delete it and report as not existing — forces a clean re-upload.
    summary = {}
    if exists and file_type == "trajectory":
        from .params import md_ase_formats
        parsed = False
        for fmt in md_ase_formats.values():
            try:
                atoms = ase.io.read(str(file_path), format=fmt, index=0)
                summary = {
                    "formula": atoms.get_chemical_formula(),
                    "num_atoms": len(atoms),
                    "num_frames": _count_trajectory_frames(str(file_path), fmt),
                }
                parsed = True
                break
            except Exception:
                continue
        if not parsed:
            # Stale invalid file — clean up
            file_path.unlink(missing_ok=True)
            exists = False

    return {"exists": exists, **summary}
