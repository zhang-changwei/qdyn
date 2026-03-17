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
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib

matplotlib.use('agg')
import matplotlib.pyplot as plt
import numpy as np
import ase.io
from ase import Atoms
from jobflow import job

from ..input import SCFInputT
from ..params import params_default, chg_name, ipt_files, stru_files
from ..input_prepare import prepare_vasp_inputs
from .run_software import run_software

# Status file names
STATUS_RUNNING = 'RUNNING'
STATUS_ENDED = 'ENDED'
STATUS_FAIL = 'FAIL'


def run_scf(
    software: str,
    parameters: SCFInputT,
    pp_path: str,
    orb_path: str,
    xdatcar_path: str,
    nodes: int = 1,
    ntasks_per_node: int = 1,
    cpus_per_task: int = 1,
    plot: bool = False,
    prepare_input_only: bool = False,
) -> List:
    """Create SCF jobs for frames from the NVE trajectory.

    This is a task distribution function (NOT @job decorated) that:
    1. Creates a Job for each batch based on batch_size and md_step

    Parameters
    ----------
    software : str
        Software name ('vasp', etc.).
    parameters : SCFInputT
        SCF calculation parameters including nscf, md_step, batch_size.
    pp_path : str
        Path to pseudopotential files.
    orb_path : str
        Path to orbital files.
    xdatcar_path : str
        Path to XDATCAR file (or other structure file). Structures are read inside
        _run_scf_task to support jobflow serialization.
    nodes : int
        Number of nodes.
    ntasks_per_node : int
        MPI tasks per node.
    cpus_per_task : int
        CPUs per task.
    plot : bool
        Whether to generate TDKS plot.
    prepare_input_only : bool
        If True, only prepare input files.

    Returns
    -------
    List[Job]
        List of SCF Job objects, one per batch.
    """

    batch_size = parameters.batch_size
    md_step = parameters.md_step
    nscf = parameters.nscf

    # Calculate total frames to process
    # Select the last nscf frames if nscf is specified
    if nscf is not None and nscf > 0:
        total_frames = min(nscf, md_step)
    else:
        total_frames = md_step

    jobs = []

    # Create a job for each batch
    for batch_idx in range(0, total_frames, batch_size):
        batch_end = min(batch_idx + batch_size, total_frames)

        # Global frame indices (0-based)
        frame_start = batch_idx
        frame_end = batch_end

        j = _run_scf_task(
            software=software,
            parameters=parameters,
            pp_path=pp_path,
            orb_path=orb_path,
            xdatcar_path=xdatcar_path,
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
def _run_scf_task(
    software: str,
    parameters: SCFInputT,
    pp_path: str,
    orb_path: str,
    xdatcar_path: str,
    frame_start: int,
    frame_end: int,
    nodes: int = 1,
    ntasks_per_node: int = 1,
    cpus_per_task: int = 1,
    prepare_input_only: bool = False,
) -> Dict:
    """Run a batch of SCF calculations for multiple structures.

    This job:
    1. Reads structures from xdatcar_path
    2. Creates subdirectories for each structure (scf_XXXX format)
    3. Prepares common input files (INCAR, KPOINTS, POTCAR)
    4. Runs SCF calculations sequentially with CHGCAR passing
    5. Manages status files for resume capability

    Parameters
    ----------
    software : str
        Software name.
    parameters : SCFInputT
        SCF parameters.
    pp_path : str
        Pseudopotential path.
    orb_path : str
        Orbital file path.
    xdatcar_path : str
        Path to XDATCAR file (or other structure file).
    frame_start : int
        Global frame index of the first structure (0-based).
    frame_end : int
        Global frame index of the last structure (0-based).
    nodes : int
        Number of compute nodes.
    ntasks_per_node : int
        MPI tasks per node.
    cpus_per_task : int
        CPUs per task.
    prepare_input_only : bool
        If True, only prepare input files without running.

    Returns
    -------
    Dict
        Dictionary containing:
        - run_dir: Working directory path for this task
        - subdirs: List of subdirectory paths for each SCF calculation
        - frame_indices: List of (global_idx, local_idx) tuples
        - successful: Number of successful SCF calculations
        - failed: List of failed frame indices
        - vbm: VBM band index (from the last successful calculation)
        - cbm: CBM band index (from the last successful calculation)
    """
    software_lower = software.lower()
    nprocs = nodes * ntasks_per_node
    nscf = parameters.nscf

    # Read structures from file
    # Determine the starting frame index in the file (select last total_frames)
    selected_structures = read_strus(
        software=software_lower,
        structure_path=xdatcar_path,
        index=-nscf,
    )

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

    # Task working directory
    task_dir = Path.cwd()
    run_dir = str(task_dir)

    # Create subdirectories and track them
    subdirs = []
    frame_indices = []  # (global_idx, local_idx)

    for local_idx, structure in enumerate(batch_structures):
        global_idx = frame_start + local_idx
        subdir_name = f"scf_{global_idx:04d}"
        subdir_path = task_dir / subdir_name

        # Create subdirectories and write structure
        subdir_path.mkdir(exist_ok=True)
        _write_stru(software_lower, structure, subdir_path)

        subdirs.append(str(subdir_path))
        frame_indices.append((global_idx, local_idx))

    # if prepare_input_only:
    #     # Copy common inputs to each subdirectory and write POSCAR
    #     for local_idx, (subdir, structure) in enumerate(zip(subdirs, batch_structures)):
    #         _write_stru(software_lower, structure, subdir)

    #     return {
    #         'run_dir': run_dir,
    #         'subdirs': subdirs,
    #         'frame_indices': frame_indices,
    #         'successful': 0,
    #         'failed': [],
    #         'vbm': 0,
    #         'cbm': 0,
    #     }

    successful = 0
    failed = []
    vbm = cbm = 0
    prev_chgcar = None
    chgcar = chg_name[software_lower]
    stru_name = stru_files[software_lower]
    files_to_copy = ipt_files[software_lower]

    # Run SCF calculations sequentially with CHGCAR passing
    for local_idx, subdir in enumerate(subdirs):
        global_idx = frame_start + local_idx

        # Check if this subdirectory already has a result
        status = _get_status(subdir)

        if status == STATUS_ENDED:
            # Already completed successfully, skip
            successful += 1
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
            prev_chgcar = os.path.join(subdir, 'CHGCAR')

        except Exception as e:
            # Mark as failed
            _set_status(subdir, STATUS_FAIL)
            failed.append(global_idx)
            # Don't propagate CHGCAR from failed calculation
            prev_chgcar = None

        finally:
            os.chdir(task_dir)

    # Extract VBM/CBM from the last successful calculation
    if successful > 0:
        # Find the last successful subdirectory
        for local_idx in range(len(subdirs) - 1, -1, -1):
            if _get_status(subdirs[local_idx]) == STATUS_ENDED:
                original_cwd = os.getcwd()
                os.chdir(subdirs[local_idx])
                try:
                    vbm, cbm = extract_band_edges()
                except:
                    vbm, cbm = 0, 0
                finally:
                    os.chdir(original_cwd)
                break

    return {
        'run_dir': run_dir,
        'subdirs': subdirs,
        'frame_indices': frame_indices,
        'successful': successful,
        'failed': failed,
        'vbm': vbm,
        'cbm': cbm,
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

    Parameters
    ----------
    software : str
        Software name ('vasp', etc.).
    structure : Atoms
        Atomic structure (used for KPOINTS generation).
    frame_start : int
        Starting index for the frame.
    parameters : SCFInputT
        SCF parameters.
    pp_path : str
        Path to pseudopotential directory.
    """

    # Create input files
    input = deepcopy(params_default['scf'][software])
    match software:
        case 'vasp':
            input['EDIFF'] = parameters.scf_thr

            # Use unified prepare_vasp_inputs function
            prepare_vasp_inputs(
                structure=structure,
                pp_path=pp_path,
                kspacing=parameters.kspacing,
                incar_dict=input,
                incar_params=parameters.parameters,
            )

        case _:
            raise NotImplementedError(
                f"Software {software} is not supported for SCF input preparation yet."
            )


def read_strus(
    software: str,
    structure_path: str,
    index: Optional[int] = None,
) -> List[Atoms]:
    """Read structure file and return ASE Atoms object.

    Parameters
    ----------
    software : str
        Software name ('vasp', 'cp2k', etc.).
    structure_path : str
        Path to structure file (e.g. CONTCAR, POSCAR, XYZ).
    format : str, optional
        File format (e.g. 'vasp', 'cp2k-xyz').

    Returns
    -------
    List[Atoms]
        List of ASE Atoms objects representing the structures.
    """
    match software:
        case 'vasp':
            structure = ase.io.read(structure_path, format='vasp-xdatcar', index=index)
        case _:
            raise ValueError(f"Unsupported software: {software}")

    return structure


def _write_stru(software: str, structure: Atoms, output_path: Path):
    """Write ASE Atoms object to a structure file.

    Parameters
    ----------
    software : str
        Software name ('vasp', 'cp2k', etc.).
    structure : Atoms
        ASE Atoms object to write.
    output_path : Path
        Path to output structure file.
    """
    match software:
        case 'vasp':
            ase.io.write(
                str(output_path / "POSCAR"), structure, vasp5=True, direct=True
            )
        case _:
            raise ValueError(f"Unsupported software: {software}")


def _get_status(subdir: str) -> Optional[str]:
    """Get the status of a subdirectory calculation.

    Parameters
    ----------
    subdir : str
        Path to subdirectory.

    Returns
    -------
    Optional[str]
        Status string (STATUS_RUNNING, STATUS_ENDED, STATUS_FAIL) or None.
    """
    for status in [STATUS_ENDED, STATUS_FAIL, STATUS_RUNNING]:
        status_file = os.path.join(subdir, status)
        if os.path.isfile(status_file):
            return status
    return None


def _set_status(subdir: str, status: str):
    """Set the status of a subdirectory calculation.

    Parameters
    ----------
    subdir : str
        Path to subdirectory.
    status : str
        Status string (STATUS_RUNNING, STATUS_ENDED, STATUS_FAIL).
    """
    # Remove old status files
    for status in [STATUS_RUNNING, STATUS_ENDED, STATUS_FAIL]:
        status_file = os.path.join(subdir, status)
        if os.path.isfile(status_file):
            os.remove(status_file)

    # Create new status file
    status_file = os.path.join(subdir, status)
    Path(status_file).touch()


def _clean_all_files(subdir: str, stru: str):
    """Remove all status files from a subdirectory except the structure file.

    Parameters
    ----------
    subdir : str
        Path to subdirectory.
    stru : str
        Name of the structure file to preserve.
    """
    for fname in os.listdir(subdir):
        if fname == stru:
            continue
        fpath = os.path.join(subdir, fname)
        if os.path.isfile(fpath):
            os.remove(fpath)


def _validate_scf_output(software: str):
    """Validate SCF calculation completed successfully.

    Checks for 'Total CPU' in OUTCAR, following the convention from
    the legacy vaspscf script.

    Raises
    ------
    RuntimeError
        If OUTCAR is missing or calculation did not complete.
    """
    match software:
        case 'vasp':
            if not os.path.isfile('OUTCAR'):
                raise RuntimeError("SCF calculation failed: OUTCAR not found.")

            with open('OUTCAR', 'r') as f:
                content = f.read()

            if 'Total CPU' not in content:
                raise RuntimeError(
                    "SCF calculation failed: OUTCAR does not contain 'Total CPU' marker. "
                    "The calculation may not have completed successfully."
                )

            # Clean up unnecessary files
            for f in ['CHG', 'vasprun.xml']:
                if os.path.isfile(f):
                    os.remove(f)
        case _:
            raise NotImplementedError(
                f"Validation for software '{software}' is not implemented."
            )


def extract_band_edges(
    outcar_path: str = 'OUTCAR',
    whichK: int = 1,
    whichS: int = 1,
) -> Tuple[int, int]:
    """Extract VBM and CBM band indices from OUTCAR.

    Parses the eigenvalue section after "E-fermi :" to find the last
    occupied band (VBM) and first unoccupied band (CBM).

    Parameters
    ----------
    outcar_path : str
        Path to OUTCAR file.
    whichK : int
        K-point index (1-based).
    whichS : int
        Spin component index (1-based).

    Returns
    -------
    Tuple[int, int]
        (vbm, cbm) - VBM and CBM band indices (1-based VASP convention).
    """
    with open(outcar_path, 'r') as f:
        OUTCAR = [line for line in f if line.strip()]

    NBANDS = NKPTS = ISPIN = 0
    for line in OUTCAR:
        if 'NBANDS' in line and 'NKPTS' in line:
            NBANDS = int(line.split()[-1])
            NKPTS = int(line.split()[3])
        if 'ISPIN  =' in line:
            ISPIN = int(line.split()[2])
            break

    # Find the last E-fermi section (for NSW=0, there's only one)
    where_Efermi = [ii for ii, line in enumerate(OUTCAR) if 'E-fermi :' in line]

    if not where_Efermi:
        raise RuntimeError("Could not find 'E-fermi' in OUTCAR.")

    ii = where_Efermi[-1]

    if ISPIN == 1:
        start = ii + 1
        end = start + (NBANDS + 2) * NKPTS + 1
    else:
        start = ii + 1
        end = start + ((NBANDS + 2) * NKPTS + 1) * ISPIN + 2

    # Filter out lines containing alphabetic characters (header lines)
    data_lines = [line for line in OUTCAR[start:end] if not re.search('[a-zA-Z]', line)]

    # Select bands for the specified spin and k-point
    offset = ((whichS - 1) * NKPTS + (whichK - 1)) * NBANDS
    band_lines = data_lines[offset : offset + NBANDS]

    vbm = 0
    cbm = 0
    for line in band_lines:
        parts = line.split()
        band_idx = int(parts[0])
        occupation = float(parts[-1])

        if occupation > 0.5:
            vbm = band_idx
        elif cbm == 0:
            cbm = band_idx

    if vbm == 0:
        raise RuntimeError("Could not determine VBM from OUTCAR eigenvalues.")
    if cbm == 0:
        cbm = vbm + 1

    return vbm, cbm


def extract_eigenvalues_from_outcar(
    outcar_path: str = 'OUTCAR',
    whichK: int = 1,
    whichS: int = 1,
) -> np.ndarray:
    """Extract eigenvalues from a single OUTCAR file.

    Parameters
    ----------
    outcar_path : str
        Path to OUTCAR.
    whichK : int
        K-point index (1-based).
    whichS : int
        Spin component index (1-based).

    Returns
    -------
    np.ndarray
        Array of eigenvalues, shape (nbands,).
    """
    with open(outcar_path, 'r') as f:
        OUTCAR = [line for line in f if line.strip()]

    NBANDS = NKPTS = ISPIN = 0
    for line in OUTCAR:
        if 'NBANDS' in line and 'NKPTS' in line:
            NBANDS = int(line.split()[-1])
            NKPTS = int(line.split()[3])
        if 'ISPIN  =' in line:
            ISPIN = int(line.split()[2])
            break

    where_Efermi = [ii for ii, line in enumerate(OUTCAR) if 'E-fermi :' in line]

    if not where_Efermi:
        raise RuntimeError(f"Could not find 'E-fermi' in {outcar_path}.")

    ii = where_Efermi[-1]

    if ISPIN == 1:
        start = ii + 1
        end = start + (NBANDS + 2) * NKPTS + 1
    else:
        start = ii + 1
        end = start + ((NBANDS + 2) * NKPTS + 1) * ISPIN + 2

    data_lines = [line for line in OUTCAR[start:end] if not re.search('[a-zA-Z]', line)]

    # Extract energies for selected spin and k-point
    offset = ((whichS - 1) * NKPTS + (whichK - 1)) * NBANDS
    band_lines = data_lines[offset : offset + NBANDS]

    eigenvalues = np.array([float(line.split()[1]) for line in band_lines])

    return eigenvalues


@job
def collect_all_scf_data(
    batch_results: List[Dict],
    plot: bool = True,
) -> Dict:
    """Collect and process data from all SCF batch calculations.

    This function is called after all batch calculations are completed
    to perform final data processing and generate comprehensive plots.

    Parameters
    ----------
    batch_results : List[Dict]
        List of results from all batch calculations.
    plot : bool
        Whether to generate final plots.

    Returns
    -------
    Dict
        Dictionary containing:
        - all_dirs: List of all SCF calculation directories (sorted by frame index)
        - summary_data: Summary of the calculations
        - images: List of generated plot file paths
    """
    # Collect all SCF directories from all batches
    all_dirs = []
    for batch_result in batch_results:
        if 'subdirs' in batch_result:
            all_dirs.extend(batch_result['subdirs'])
        elif 'run_dir' in batch_result:
            all_dirs.append(batch_result['run_dir'])

    # Sort directories to ensure chronological order
    all_dirs.sort()

    # Perform final data processing
    summary_data = {
        'total_calculations': len(all_dirs),
        'batch_count': len(batch_results),
        'directories': all_dirs,
        'successful': sum(r.get('successful', 0) for r in batch_results),
        'failed_frames': [f for r in batch_results for f in r.get('failed', [])],
    }

    # Generate final plots if requested
    images = []
    if plot and all_dirs:
        # Find VBM from the last successful calculation
        vbm = cbm = 0
        for batch_result in reversed(batch_results):
            if batch_result.get('vbm', 0) > 0:
                vbm = batch_result['vbm']
                cbm = batch_result['cbm']
                break

        if vbm == 0:
            # Try to extract from last directory
            last_dir = all_dirs[-1]
            original_cwd = os.getcwd()
            try:
                os.chdir(last_dir)
                vbm, cbm = extract_band_edges()
            except:
                vbm, cbm = 1, 2
            finally:
                os.chdir(original_cwd)

        # Generate TDKS plot for all directories
        tdksgen_image = plot_scf_tdks(all_dirs, vbm, filename='final_tdksgen.png')
        images.append(tdksgen_image)

        # Generate additional summary plots
        summary_image = plot_summary_data(all_dirs, filename='scf_summary.png')
        images.append(summary_image)

    return {
        'all_dirs': all_dirs,
        'summary_data': summary_data,
        'images': images,
    }


def plot_summary_data(
    all_run_dirs: List[str],
    filename: str = 'scf_summary.png',
) -> str:
    """Plot a summary of SCF calculations across all directories.

    Parameters
    ----------
    all_run_dirs : List[str]
        List of SCF run directories in chronological order.
    filename : str
        Output plot filename.

    Returns
    -------
    str
        Path to saved plot file.
    """
    # Collect energies from all frames
    total_energies = []
    convergence_status = []

    for d in all_run_dirs:
        outcar_path = os.path.join(d, 'OUTCAR')
        if os.path.isfile(outcar_path):
            # Extract total energy from OUTCAR
            with open(outcar_path, 'r') as f:
                content = f.read()

            # Find total energies in OUTCAR
            energy_matches = re.findall(r'T\=\s*\d+\s+E\=\s*[-+]?\d+\.\d+', content)
            if energy_matches:
                last_energy_line = energy_matches[-1]
                total_energy = float(last_energy_line.split()[-1])
                total_energies.append(total_energy)
            else:
                total_energies.append(np.nan)

            # Check convergence status
            if 'EDIFF' in content and 'energy(sigma->0)' in content:
                convergence_status.append(True)
            else:
                convergence_status.append(False)

    if not total_energies:
        raise RuntimeError("No total energy values found for summary plotting.")

    # Plot total energy vs frame index
    fig, ax = plt.subplots(figsize=(10, 6))

    frame_indices = list(range(len(total_energies)))
    ax.plot(frame_indices, total_energies, 'o-', color='b', alpha=0.7, markersize=3)

    ax.set_xlabel('SCF Frame Index')
    ax.set_ylabel('Total Energy (eV)')
    ax.set_title('Total Energy Evolution in SCF Calculations')
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(filename, dpi=300)
    plt.close()

    return os.path.abspath(filename)


def plot_scf_tdks(
    all_run_dirs: List[str],
    vbm: int,
    filename: str = 'tdks.png',
) -> str:
    """Plot time-dependent Kohn-Sham eigenvalues (TDKS) from SCF calculations.

    Reads OUTCAR files from all SCF directories, extracts eigenvalues,
    and plots band energies versus time step. Energies are shifted
    relative to the VBM energy.

    Parameters
    ----------
    all_run_dirs : List[str]
        List of SCF run directories in chronological order.
    vbm : int
        VBM band index (1-based).
    filename : str
        Output plot filename.

    Returns
    -------
    str
        Path to saved plot file.
    """
    # Collect eigenvalues from all frames
    all_eigenvalues = []
    for d in all_run_dirs:
        outcar_path = os.path.join(d, 'OUTCAR')
        if os.path.isfile(outcar_path):
            eigvals = extract_eigenvalues_from_outcar(outcar_path)
            all_eigenvalues.append(eigvals)

    if not all_eigenvalues:
        raise RuntimeError("No valid OUTCAR files found for TDKS plotting.")

    # Stack into [nframe, nband] array
    TDKS = np.array(all_eigenvalues)
    nsw = TDKS.shape[0]
    nband = TDKS.shape[1]

    # VBM energy: average VBM eigenvalue across all frames
    vbm_idx = vbm - 1  # Convert to 0-based
    cbm_idx = vbm  # CBM is next band (0-based)

    vbm_energy = np.average(TDKS[:, vbm_idx])
    cbm_energy = np.average(TDKS[:, cbm_idx]) if cbm_idx < nband else vbm_energy
    band_gap = cbm_energy - vbm_energy

    # Shift energies relative to VBM
    TDKS -= vbm_energy

    # Save band gap info
    with open('VBCB', 'w') as f:
        f.write(f"CBINDEX = {vbm + 1}\n")
        f.write(f"VBM_energy = {vbm_energy:.6f}\n")
        f.write(f"CBM_energy = {cbm_energy:.6f}\n")
        f.write(f"Band_gap   = {band_gap:.6f}\n")

    # Plot
    dt = 1.0
    TIME = np.arange(nsw) * dt

    fig = plt.figure()
    fig.set_size_inches(6.0, 4.0)
    ax = plt.subplot(111)

    for ib in range(nband):
        ax.plot(TIME, TDKS[:, ib], ls='-', lw=1.0, color='b', alpha=0.7)

    ax.set_ylim(-0.5 * band_gap, 1.5 * band_gap)
    ax.set_xlabel('Time [fs]')
    ax.set_ylabel('Energy [eV]')
    ax.set_title('Time-Dependent KS Eigenvalues')

    plt.tight_layout()
    plt.savefig(filename, dpi=360)
    plt.close()

    return os.path.abspath(filename)
