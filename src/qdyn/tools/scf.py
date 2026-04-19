"""
SCF (Self-Consistent Field) calculation module for NAMD workflow.

This module handles static SCF calculations on structures extracted from NVE
trajectory. It supports:
- Batch processing with configurable batch size
- Sequential CHGCAR passing between frames for faster convergence
- Status file tracking (RUNNING, ENDED, FAIL) for resume capability
"""

import os
import re
import logging
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Tuple, Any, TYPE_CHECKING

import matplotlib

matplotlib.use('agg')
import matplotlib.pyplot as plt
import natsort
import numpy as np
import ase.io
from ase import Atoms
from jobflow import job, Job

from ..input import SCFInputT
from ..params import params_default, chg_name, ipt_files, stru_files
from ..input_prepare import prepare_vasp_inputs
from .nve import read_strus
from .run_software import run_software

# Status file names
STATUS_RUNNING = 'RUNNING'
STATUS_ENDED = 'ENDED'
STATUS_FAIL = 'FAIL'


def qdyn_scf(
    software: str,
    parameters: SCFInputT,
    pp_path: str,
    orb_path: str,
    traj_file_path: str,
    traj_format: str = 'vasp-xdatcar',
    nodes: int = 1,
    ntasks_per_node: int = 1,
    cpus_per_task: int = 1,
    plot: bool = False,
    prepare_input_only: bool = False,
) -> List[Job]:
    """Create SCF jobs for frames from the NVE trajectory.

    This is a task distribution function (NOT @job decorated) that:
    1. Creates a Job for each batch based on batch_size and md_step

    Args:
        software: Software name ('vasp', etc.).
        parameters: SCF calculation parameters including scf_step, md_step,
            batch_size.
        pp_path: Path to pseudopotential files.
        orb_path: Path to orbital files.
        traj_file_path: Path to the trajectory file (e.g. XDATCAR for VASP).
        traj_format: Format of the trajectory file.
        nodes: Number of nodes.
        ntasks_per_node: MPI tasks per node.
        cpus_per_task: CPUs per task.
        plot: Whether to generate TDKS plot.
        prepare_input_only: If True, only prepare input files.

    Returns:
        List of SCF Job objects, one per batch.
    """

    batch_size = parameters.batch_size
    total_frames = parameters.scf_step

    jobs = []

    # Create a job for each batch
    for batch_idx in range(0, total_frames, batch_size):
        batch_end = min(batch_idx + batch_size, total_frames)

        # Global frame indices (0-based)
        frame_start = batch_idx
        frame_end = batch_end

        j = qdyn_scf_task(
            software=software,
            parameters=parameters,
            pp_path=pp_path,
            orb_path=orb_path,
            traj_file_path=traj_file_path,
            traj_format=traj_format,
            frame_start=frame_start,
            frame_end=frame_end,
            nodes=nodes,
            ntasks_per_node=ntasks_per_node,
            cpus_per_task=cpus_per_task,
            prepare_input_only=prepare_input_only,
        )
        jobs.append(j)

    return jobs


@job
def qdyn_scf_task(
    software: str,
    parameters: SCFInputT,
    pp_path: str,
    orb_path: str,
    traj_file_path: str,
    traj_format: str = 'vasp-xdatcar',
    frame_start: int = 0,
    frame_end: int = 0,
    nodes: int = 1,
    ntasks_per_node: int = 1,
    cpus_per_task: int = 1,
    prepare_input_only: bool = False,
) -> Dict:
    """Run a batch of SCF calculations for multiple structures.

    This job:
    1. Reads structures from the trajectory file (e.g. XDATCAR)
    2. Creates subdirectories for each structure (scf_XXXX format)
    3. Prepares common input files (INCAR, KPOINTS, POTCAR)
    4. Runs SCF calculations sequentially with CHGCAR passing
    5. Manages status files for resume capability

    Args:
        software: Software name.
        parameters: SCF parameters.
        pp_path: Pseudopotential path.
        orb_path: Orbital file path.
        traj_file_path: Path to the trajectory file (e.g. XDATCAR for VASP).
        traj_format: Format of the trajectory file (e.g. 'vasp-xdatcar').
        frame_start: Global frame index of the first structure (0-based).
        frame_end: Global frame index of the last structure (0-based).
        nodes: Number of compute nodes.
        ntasks_per_node: MPI tasks per node.
        cpus_per_task: CPUs per task.
        prepare_input_only: If True, only prepare input files without running.

    Returns:
        Dict:
        - run_dir: Working directory path for this task
        - frame_range: (start, end) tuple of frame indices (inclusive)
        - successful: Number of successful SCF calculations
        - failed: List of failed frame indices
        - vbm: VBM band index (from the last successful calculation)
        - cbm: CBM band index (from the last successful calculation)
    """
    software_lower = software.lower()
    nprocs = nodes * ntasks_per_node
    scf_step = parameters.scf_step

    all_strus = read_strus(traj_format, traj_file_path=traj_file_path)
    selected_structures = all_strus[-scf_step:]
    batch_structures = selected_structures[frame_start:frame_end]
    n_frames = len(batch_structures)

    # Prepare common input files once (these will be copied to each subdir)
    _prepare_scf_input(
        software=software_lower,
        structure=batch_structures[0],  # Use first structure for KPOINTS generation
        parameters=parameters,
        pp_path=pp_path,
        orb_path=orb_path,
    )

    if prepare_input_only:
        return {
            'run_dir': str(Path.cwd()),
            'successful': 0,
            'failed': [],
        }

    # Task working directory
    task_dir = Path.cwd()
    run_dir = str(task_dir)

    # Create subdirectories
    subdirs = []
    numdigit = len(str(scf_step))

    for local_idx, structure in enumerate(batch_structures, start=1):
        global_idx = frame_start + local_idx
        subdir_name = f"scf_{global_idx:0{numdigit}d}"
        subdir_path = task_dir / subdir_name

        # Create subdirectories and write structure
        subdir_path.mkdir(exist_ok=True)
        _write_stru(software_lower, structure, subdir_path)

        subdirs.append(str(subdir_path))

    successful = 0
    failed = []
    prev_chgcar = None
    chgcar = chg_name[software_lower]
    stru_name = stru_files[software_lower]
    files_to_copy = ipt_files[software_lower]

    # Run SCF calculations sequentially with CHGCAR passing
    for local_idx, subdir in enumerate(subdirs, start=1):
        global_idx = frame_start + local_idx

        # Check if this subdirectory already has a result
        status = _get_status(subdir)

        if status == STATUS_ENDED:
            # Already completed successfully, skip
            successful += 1
            # Restore CHGCAR relay for resume scenarios
            prev_chgcar = None
            resume_chgcar = os.path.join(subdir, chgcar)
            if os.path.isfile(resume_chgcar):
                prev_chgcar = resume_chgcar
            continue

        if status in [STATUS_RUNNING, STATUS_FAIL]:
            # Previous run was interrupted, clean up and restart
            _clean_all_files(subdir, stru_name)

        # Prepare this subdirectory - copy input files from task_dir
        for fname in files_to_copy:
            src = fname
            dst = os.path.join(subdir, fname)
            shutil.copy2(src, dst)

        # Copy CHGCAR from previous successful calculation for faster convergence
        if prev_chgcar is not None:
            shutil.copy2(prev_chgcar, os.path.join(subdir, chgcar))

        # Mark as running
        _set_status(subdir, STATUS_RUNNING)

        # Change to subdirectory and run
        os.chdir(subdir)

        try:
            # Run VASP
            run_software(
                software=software_lower, nprocs=nprocs, is_alle=parameters.is_alle
            )

            # Validate output
            _validate_scf_output(software_lower)

            # Mark as ended
            _set_status(subdir, STATUS_ENDED)
            successful += 1

            # Update prev_chgcar for next iteration
            prev_chgcar = os.path.join(subdir, chgcar)

        except Exception as e:
            # Mark as failed
            logging.error(f"SCF calculation failed for frame {global_idx}: {e}")
            _set_status(subdir, STATUS_FAIL)
            failed.append(global_idx)
            break

        finally:
            os.chdir(task_dir)

    if successful < n_frames:
        raise ValueError(
            f"SCF calculation failed in frame indice: {failed}. Please check the "
            "respective subdirectories for details."
        )

    # frame_end is exclusive, so actual last frame index is frame_end - 1
    # prepare_namd.py expects inclusive range: (start, end)
    return {
        'run_dir': run_dir,
        'successful': successful,
        'failed': failed,
    }


def _prepare_scf_input(
    software: str,
    structure: Atoms,
    parameters: SCFInputT,
    pp_path: str,
    orb_path: str,
):
    """Prepare common input files (INCAR, KPOINTS, POTCAR) in current directory.

    These files will be copied to each subdirectory.

    Args:
        software: Software name ('vasp', etc.).
        structure: Atomic structure (used for KPOINTS generation).
        parameters: SCF parameters.
        pp_path: Path to pseudopotential directory.
        orb_path: Path to orbital files.
    """

    # Create input files
    input = deepcopy(params_default['scf'][software])
    if software == 'vasp':
        input['EDIFF'] = parameters.scf_thr

        # Use unified prepare_vasp_inputs function
        prepare_vasp_inputs(
            structure=structure,
            pp_path=pp_path,
            kspacing=parameters.kspacing,
            incar_dict=input,
            incar_params=parameters.parameters,
        )
    else:
        raise NotImplementedError(
            f"Software {software} is not supported for SCF input preparation yet."
        )


def _write_stru(software: str, structure: Atoms, output_path: Path):
    """Write ASE Atoms object to a structure file.

    Args:
        software: Software name ('vasp', 'cp2k', etc.).
        structure: ASE Atoms object to write.
        output_path: Path to output structure file.
    """
    if software == 'vasp':
        ase.io.write(
            str(output_path / "POSCAR"), structure, vasp5=True, direct=True
        )
    else:
        raise ValueError(f"Unsupported software: {software}")


def _get_status(subdir: str) -> str | None:
    """Get the status of a subdirectory calculation.

    Args:
        subdir: Path to subdirectory.

    Returns:
        Status string (STATUS_RUNNING, STATUS_ENDED, STATUS_FAIL) or None.
    """
    for status in [STATUS_ENDED, STATUS_FAIL, STATUS_RUNNING]:
        status_file = os.path.join(subdir, status)
        if os.path.isfile(status_file):
            return status
    return None


def _set_status(subdir: str, status: str):
    """Set the status of a subdirectory calculation.

    Args:
        subdir: Path to subdirectory.
        status: Status string (STATUS_RUNNING, STATUS_ENDED, STATUS_FAIL).
    """
    # Remove old status files
    for old_status in [STATUS_RUNNING, STATUS_ENDED, STATUS_FAIL]:
        status_file = os.path.join(subdir, old_status)
        if os.path.isfile(status_file):
            os.remove(status_file)

    # Create new status file
    status_file = os.path.join(subdir, status)
    Path(status_file).touch()


def _clean_all_files(subdir: str, stru: str):
    """Remove all status files from a subdirectory except the structure file.

    Args:
        subdir: Path to subdirectory.
        stru: Name of the structure file to preserve.
    """
    for fname in os.listdir(subdir):
        if fname == stru:
            continue
        fpath = os.path.join(subdir, fname)
        if os.path.isfile(fpath):
            os.remove(fpath)


def _validate_scf_output(software: str):
    """Validate SCF calculation completed successfully.

    Checks for 'Total CPU' and SCF convergence in OUTCAR, reading only
    the file tail for efficiency.

    Raises:
        RuntimeError: If OUTCAR is missing or calculation did not
            complete/converge.
    """
    if software == 'vasp':
        if not os.path.isfile('OUTCAR'):
            raise RuntimeError("SCF calculation failed: OUTCAR not found.")

        with open('OUTCAR', 'rb') as f:
            content = f.read()

        # Check completion marker
        if b'Total CPU' not in content:
            raise RuntimeError(
                "SCF calculation failed: OUTCAR does not contain 'Total CPU' marker. "
                "The calculation may not have completed successfully."
            )

        # Check SCF convergence
        if b'aborting loop because EDIFF is reached' not in content:
            # Look for common convergence failure markers
            # if b'WARNING in EDDAV' in content or b'ZBRENT: fatal error' in content:
            #     raise RuntimeError(
            #         "SCF calculation failed: SCF did not converge. "
            #         "Check OUTCAR for convergence errors."
            #     )
            raise RuntimeError(
                "SCF calculation failed: SCF did not converge. "
                "OUTCAR does not contain 'aborting loop because EDIFF is reached' marker."
            )

        # Check WAVECAR file size
        if not os.path.isfile('WAVECAR'):
            raise RuntimeError("SCF calculation failed: WAVECAR not found.")
        if os.path.getsize('WAVECAR') == 0:
            raise RuntimeError(
                "SCF calculation failed: WAVECAR is empty. "
                "The calculation may not have completed successfully."
            )

        # Clean up unnecessary files
        for f in ['CHG', 'vasprun.xml']:
            if os.path.isfile(f):
                os.remove(f)
    else:
        raise NotImplementedError(
            f"Validation for software '{software}' is not implemented."
        )
