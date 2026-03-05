# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

QDYN is a Python toolkit for automating **non-adiabatic quasiparticle dynamics** workflows on HPC clusters. It is being rewritten under `src/` to support task management, multiple quantum chemistry backends, and a REST API for remote job control.

## Running the Server

```bash
python main.py --server        # start the job-manager API on 0.0.0.0:8000
python main.py                 # run the standalone workflow entry point
```

**Prerequisites:**
- SLURM cluster with `sbatch` and `sacct`
- Python environment with `fastapi`, `uvicorn[standard]`
- Quantum chemistry executables as required by the workflow (VASP, Hefei-NAMD, etc.)

## Architecture

### `src/` — New Core Package

| File | Role |
|------|------|
| `job_manager.py` | SLURM task/job management + FastAPI server (`app`). Runs a background poll loop that submits queued jobs and updates their status via `sacct`. |
| `main_workflow.py` | Workflow orchestration (in progress). |
| `constants.py` | Shared constants (e.g. `JOB_MANAGER_POLL_INTERVAL = 30`). |
| `__init__.py` | Package marker. |

### Job Manager (`src/job_manager.py`)

**Domain models:**
- `Task` — a quota-bounded resource pool (`quota` = max nodes in use at once, `used` = currently occupied nodes).
- `Job` — a single SLURM submission bound to a `Task`. Statuses: `waiting → pending → running → <terminal>` (SLURM states lowercased: `completed`, `failed`, `cancelled`, …).

**`SlurmManager`** (singleton `manager`):
- `add_task(quota, config)` — create a `Task`; on the very first call, also registers a bootstrap job that runs `src/main.py`.
- `delete_task(task_id)` — remove a task by UUID.
- `register_job(task_id, command, working_dir, partition, nodes, ntasks_per_node, cpus_per_task, [dependency, mem, exclusive])` — write a `submit.sh` SLURM script and enqueue the job. Returns the job UUID.
- `submit_jobs()` — called each poll cycle; submits `waiting` jobs that fit within their task's quota using `sbatch --parsable`.
- `check_job_status()` — called each poll cycle; queries `sacct` and updates job statuses; decrements `task.used` when a job leaves the active state.
- `start_polling()` / `stop_polling()` — manage the asyncio background loop (started/stopped via FastAPI `lifespan`).

### REST API (FastAPI, default port 8000)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/tasks` | Create a task `{"quota": N}` → returns `TaskInfo` |
| `GET` | `/tasks` | List all tasks |
| `DELETE` | `/tasks/{task_id}` | Delete a task |
| `POST` | `/jobs` | Register a job (see `JobRegister` schema) → returns `JobInfo` |
| `GET` | `/jobs` | List all jobs |
| `GET` | `/jobs/{job_uuid}` | Get a single job |

Interactive docs available at `http://localhost:8000/docs` when the server is running.

### Entry Point (`main.py`)

- `python main.py --server` → calls `serve()`, which starts uvicorn with `src.job_manager:app`.
- `python main.py` → calls `main()` (standalone workflow, placeholder).

### Legacy Code (`namd_server_test/`)

The original 5-step pipeline (SR → NVT → NVE → WAVECAR → Hefei-NAMD) lives here. It is **not** integrated with the new `src/` package yet and is kept for reference. Entry point: `namd_server_test/run_workflow_test.py`.

## Key Patterns

- Job quota enforcement is in-memory; `task.used` is decremented as soon as `sacct` reports a non-active state.
- SLURM scripts are written to `<working_dir>/submit.sh` before submission; `--parsable` ensures a clean numeric job ID is returned.
- The poll interval is controlled by `JOB_MANAGER_POLL_INTERVAL` in `src/constants.py`.
