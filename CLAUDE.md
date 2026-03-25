# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

QDYN is a Python toolkit for non-adiabatic quasiparticle dynamics (NAMD) simulations. It orchestrates first-principles DFT calculations (VASP, CP2K, SIESTA, ABACUS, OpenMX) through a multi-step workflow: NVT → NVE → SCF → PRE_NAMD → NAMD. The system uses jobflow/jobflow-remote for workflow management, SLURM for HPC job scheduling, and FastAPI for its web API.

## Common Commands

```bash
# Install dependencies
uv sync

# Start the FastAPI server (default config: config/qdyn.yaml)
python main.py --server

# Start with explicit config
python main.py --server --config /path/to/qdyn.yaml

# Run locally (CLI mode)
python main.py
```

```bash
# Run auth tests
uv run pytest tests/qdyn/test_auth.py -v
```

## Architecture

### Workflow Pipeline

The core workflow (`MainWorkflow` in `src/qdyn/main_workflow.py`) builds a DAG of jobflow `@job`-decorated functions:

1. **NVT** (`src/qdyn/tools/nvt.py`) — NVT molecular dynamics with auto-retry on temperature non-convergence (up to 10 retries)
2. **NVE** (`src/qdyn/tools/nve.py`) — NVE molecular dynamics; extracts multiple structures from XDATCAR for batch SCF
3. **SCF** (`src/qdyn/tools/scf.py`) — Static SCF calculations on each NVE snapshot
4. **PRE_NAMD** (`src/qdyn/tools/prepare_namd.py`) — Extracts eigenvalues/NACs via CANAC, computes dephasing times
5. **NAMD** (`src/qdyn/tools/namd.py`) — Runs surface hopping dynamics (FSSH or DISH methods)

Steps must be contiguous and sequential. The workflow supports resume from a previous task_id.

### Parameter Override Chain

Default params (`src/qdyn/params.py`) → Pydantic input fields (`src/qdyn/input.py`) → raw parameter string (highest priority)

### Input/Output

- **Input models** (`src/qdyn/input.py`): Pydantic models per step (NVTInputT, NVEInputT, SCFInputT, etc.). Each has a `to_vasp_incar()` method.
- **Input preparation** (`src/qdyn/input_prepare.py`): Generates VASP files (POSCAR, KPOINTS, POTCAR, INCAR). Uses ASE for structure I/O and pymatgen for INCAR.
- **Output processing** (`src/qdyn/output_postprocess.py`): Parses OSZICAR for MD data in a unified format regardless of DFT code.

### CANAC Library (`src/qdyn/tools/libcanac/`)

Core library for computing non-adiabatic couplings. Each DFT code has its own wavefunction handler (`vaspwfc.py`, `cp2kwfc.py`, `siestawfc.py`, `abacuswfc.py`, etc.). The Hungarian algorithm (`mod_hungarian.py`) handles band reordering.

### Configuration

Machine config lives in `config/qdyn.yaml` (or `$QDYN_CONFIG` env var). It defines SLURM partition, modules to load, pseudopotential paths, per-step resource allocations (nodes, tasks, CPUs), and auth settings.

Key auth config keys (`auth` section):
- `secret_key`: JWT secret (auto-generated if empty)
- `token_expire_hours`: JWT lifetime (default `24`)

User DB path is configured under `basic.user_db_path` (default `data/qdyn_users.db`).

### FastAPI Server

Defined in `src/qdyn/app.py`. A lifespan context manager initializes `MainWorkflow`, the auth system, and SQLite persistence. The workflow logic lives in `src/qdyn/main_workflow.py`.

#### API Endpoints

| Method | Path | Auth | Description |
|--------|------|:----:|-------------|
| POST | `/auth/register` | No | Register user, returns JWT |
| POST | `/auth/login` | No | Login, returns JWT |
| POST | `/submit` | Yes | Submit a workflow task |
| GET | `/tasks` | Yes | List current user's tasks |
| GET | `/tasks/{task_id}/jobs` | Yes | List jobs by step for a task |
| DELETE | `/tasks/{task_id}` | Yes | Delete a task record |
| GET | `/tasks/{task_id}/jobs/{job_uuid}/output` | Yes | Get job output |

### Error Handling

Error classes in `src/qdyn/main_workflow.py` are caught by `src/qdyn/app.py` and mapped to HTTP responses:

| Exception | Meaning | HTTP Status |
|-----------|---------|:-----------:|
| `ValidationError` | Invalid user input: bad steps, missing structure, non-contiguous steps | 422 |
| `ConfigError` | Server-side qdyn.yaml misconfiguration: missing resource/module/path sections | 500 |
| `ResumeError` | Resume failure: previous task_id or job output not found | 404 |
| `NotSupportedError` | Requested method/feature is not yet implemented | 501 |

Pre-flight validation (`MainWorkflow._validate_input()`) runs before workflow construction and checks steps validity, resume consistency, structure availability, and config completeness.

### Auth & Database

- **Auth package** (`src/qdyn/auth/`): JWT (PyJWT + bcrypt), FastAPI dependencies, register/login router
- **Database** (`src/qdyn/database.py`): `QdynDB` class (singleton `qdyndb`) — SQLite for user accounts and task ownership persistence
- **Security** (`src/qdyn/auth/security.py`): `configure()` sets secret key + token expiry at startup

## Key Conventions

- All computational steps use jobflow's `@job` decorator for dependency tracking and output storage
- Pydantic models for all user-facing input validation
- `namd_server_test/` is legacy reference code — do not modify
- Git workflow: develop on `local` branch, merge to `main` before push
- Package manager is `uv` (not pip)
- Python >= 3.10, < 3.13 required
- Package root is `src/qdyn/` (import as `from qdyn.xxx import ...`)
- Tests live in `tests/qdyn/`; run with `PYTHONPATH=src` or install in dev mode

## Adding Support for a New DFT Code

1. Add the software name to the `Literal` type in `src/qdyn/input.py`
2. Add module/export/resource config in `config/qdyn.yaml`
3. Create `prepare_{software}_inputs()` in `src/qdyn/input_prepare.py`
4. Add step-specific input prep functions in the tool modules
5. Add default parameter templates in `src/qdyn/params.py`
6. Add a wavefunction handler in `src/qdyn/tools/libcanac/`
