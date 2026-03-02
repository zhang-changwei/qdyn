# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

QDYN is a Python toolkit that automates **non-adiabatic quasiparticle dynamics** workflows on HPC clusters. It orchestrates a 5-step pipeline combining VASP (DFT) calculations with Hefei-NAMD simulations, submitted via SLURM.

## Running the Workflow

There is no traditional build step. Run the test workflow directly:

```bash
cd namd_server_test
python run_workflow_test.py
```

**Prerequisites for full execution:**
- SLURM cluster with `sbatch` and `sacct`
- VASP, vaspkit, and Hefei-NAMD executables
- Python environment with `ase`, `numpy`, `matplotlib`
- Intel compiler + MPI modules and `ML_DFT` conda environment
- A `POSCAR` file placed at `./jobs/POSCAR`

The test script creates a workflow with job ID `"111"`, polls status every 30 seconds, and logs to `workflow_test.log`.

## Architecture

### 5-Step Computational Pipeline

```
Step 1: Structure Optimization (SR/VASP)
   ↓
Step 2: NVT Equilibration (constant-temperature MD/VASP)
   ↓
Step 3: NVE Trajectory (microcanonical MD/VASP)
   ↓
Step 4: WAVECAR Calculation (SCF along trajectory/VASP)
   ↓
Step 5: Hefei-NAMD Simulation (DISH or FSSH method)
```

### Core Modules (`namd_server_test/`)

| File | Role |
|------|------|
| `workflow_manager.py` | Central orchestrator; manages all 5 steps sequentially, handles retries and failures |
| `slurm_manager.py` | SLURM interface: `submit_job()`, `job_completed()`, `job_successful()` via `sacct` |
| `prepare.py` | Generates input files for each step; uses vaspkit for POTCAR/KPOINTS; templates from `templates/` |
| `postprocess.py` | Validates results after each step; checks convergence (±10% temperature for NVT); generates plots |
| `utils.py` | `run_command()`, `check_status()`, `update_queue()` (selects SLURM queue with most idle nodes) |
| `config.py` | All parameters: paths, SLURM scripts, defaults (300K, 1000 NVT steps, 1000 NVE steps, DISH method) |

### Job Status Tracking

Status is file-based within each step directory:
- `RUNNING` → calculation in progress
- `ENDED` → calculation completed (pending validation)
- `SUCCESSFUL` → passed validation checks
- `FAILED` → error encountered

`WorkflowManager` reads/writes these files; `check_status()` in `utils.py` handles all status transitions.

### Configuration

All parameters are in `config.py`:
- `DEFAULT_PARAMETERS`: temperature (300K), NVT/NVE step counts, WAVECAR sampling (500 steps), simulation method (DISH/FSSH), INIBAND
- `NAMD_INP`: band range (0–8), sampling points (50), hole vs. electron simulation
- `SLURM_SCRIPTS`: maps step names to submission scripts in `scripts/`

INCAR templates live in `templates/VASP/` (one per step). NAMD input templates in `templates/NAMD/`.

### Key Patterns

- `prepare.py::genescf()` extracts POSCAR snapshots from NVE trajectory for batch SCF
- NVT re-runs automatically if convergence criteria fail (recursive retry in `WorkflowManager`)
- `update_queue()` dynamically selects the least-loaded SLURM partition at submission time
- The deprecated `namd.py` (Flask server) is not used; `run_workflow_test.py` is the entry point
