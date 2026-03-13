import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib

matplotlib.use('agg')
import matplotlib.pyplot as plt
import numpy as np
from ase import Atoms
from jobflow import job

from ..input import SCFInputT
from ..params import params_default
from ..input_prepare import prepare_vasp_inputs
from .run_vasp import run_vasp


def run_scf(
    software: str,
    parameters: SCFInputT,
    pp_path: str,
    orb_path: str,
    structures,
    nodes: int = 1,
    ntasks_per_node: int = 1,
    cpus_per_task: int = 1,
    plot: bool = False,
    prepare_input_only: bool = False,
) -> List:
    """Create SCF jobs for each frame from the NVE trajectory.

    This is a regular function (NOT @job decorated) that returns a list
    of Job objects, one per SCF frame. The last nscf frames of the NVE
    trajectory are used.

    Parameters
    ----------
    software : str
        Software name ('vasp', etc.).
    parameters : SCFInputT
        SCF calculation parameters including nscf.
    pp_path : str
        Path to pseudopotential files.
    orb_path : str
        Path to orbital files.
    structures : List[Atoms] or OutputReference
        Structures from NVE trajectory (XDATCAR).
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
        List of SCF Job objects.
    """
    nscf = parameters.nscf
    jobs = []

    for i in range(nscf):
        # Select structures from the end of NVE trajectory
        # structures[-(nscf - i)] gives the last nscf frames in order
        struct = structures[-(nscf - i)]

        # For the last job, collect all previous run_dirs for plotting
        all_run_dirs = None
        if i == nscf - 1 and plot:
            all_run_dirs = [j.output['run_dir'] for j in jobs]

        j = _run_single_scf(
            software=software,
            parameters=parameters,
            pp_path=pp_path,
            orb_path=orb_path,
            structure=struct,
            nodes=nodes,
            ntasks_per_node=ntasks_per_node,
            cpus_per_task=cpus_per_task,
            plot=plot,
            is_last=(i == nscf - 1),
            all_run_dirs=all_run_dirs,
            prepare_input_only=prepare_input_only,
        )
        jobs.append(j)

    return jobs


@job
def _run_single_scf(
    software: str,
    parameters: SCFInputT,
    pp_path: str,
    orb_path: str,
    structure: Atoms,
    nodes: int = 1,
    ntasks_per_node: int = 1,
    cpus_per_task: int = 1,
    plot: bool = False,
    is_last: bool = False,
    all_run_dirs: Optional[List[str]] = None,
    prepare_input_only: bool = False,
) -> Dict:
    """Run a single static SCF calculation for one MD frame.

    Each SCF job writes WAVECAR and OUTCAR needed by the subsequent
    CA-NAC calculation in prepare_namd.

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
    structure : Atoms
        Atomic structure for this frame.
    nodes : int
        Number of compute nodes.
    ntasks_per_node : int
        MPI tasks per node.
    cpus_per_task : int
        CPUs per task.
    plot : bool
        Whether to generate plots.
    is_last : bool
        Whether this is the last SCF job (triggers TDKS plotting).
    all_run_dirs : List[str], optional
        Run directories of all previous SCF jobs (for plotting).
    prepare_input_only : bool
        If True, only prepare input files without running.

    Returns
    -------
    Dict
        Dictionary containing:
        - run_dir: Working directory path
        - software: Software name
        - vbm: VBM band index (1-based)
        - cbm: CBM band index (1-based)
        - images: List of plot file paths
    """
    software_lower = software.lower()
    nprocs = nodes * ntasks_per_node

    # Prepare input files
    _prepare_scf_input(
        software=software_lower,
        structure=structure,
        parameters=parameters,
        pp_path=pp_path,
        orb_path=orb_path,
    )

    if prepare_input_only:
        return {
            'run_dir': str(Path.cwd()),
            'software': software,
            'vbm': 0,
            'cbm': 0,
            'images': [],
        }

    # Run VASP
    run_vasp(nprocs=nprocs)

    # Validate output
    _validate_scf_output()

    # Clean up unnecessary large files
    for f in ['CHG', 'vasprun.xml']:
        if os.path.isfile(f):
            os.remove(f)

    # Extract VBM/CBM band indices
    vbm, cbm = _extract_band_edges()

    images = []
    # TDKS plot for the last job
    if is_last and plot and all_run_dirs is not None:
        all_dirs = all_run_dirs + [str(Path.cwd())]
        image = plot_scf_tdks(all_dirs, vbm, filename='tdks.png')
        images.append(image)

    return {
        'run_dir': str(Path.cwd()),
        'software': software,
        'vbm': vbm,
        'cbm': cbm,
        'images': images,
    }


def _prepare_scf_input(
    software: str,
    structure: Atoms,
    parameters: SCFInputT,
    pp_path: str,
    orb_path: str,
):
    """Prepare input files for a static SCF calculation.

    Key INCAR settings for SCF:
    - NSW=0, IBRION=-1: static calculation (no ionic relaxation)
    - LWAVE=True: write WAVECAR (needed by CA-NAC)
    - LCHARG=True: write CHGCAR
    - ICHARG=1: read CHGCAR if available
    - ISYM=0: no symmetry (required for NAC calculation)

    Parameters
    ----------
    software : str
        Software name ('vasp', etc.).
    structure : Atoms
        Atomic structure.
    parameters : SCFInputT
        SCF parameters.
    pp_path : str
        Path to pseudopotential directory.
    orb_path : str
        Path to orbital files.
    """
    input_params = deepcopy(params_default['scf'][software])
    match software:
        case 'vasp':
            # Static SCF settings
            input_params['NSW'] = 0
            input_params['IBRION'] = -1
            input_params['LWAVE'] = True
            input_params['LCHARG'] = True
            input_params['ICHARG'] = 1
            input_params['ISYM'] = 0

            # Apply user parameters from SCFInputT
            input_params['NELM'] = parameters.nelm
            input_params['EDIFF'] = parameters.scf_thr
            input_params['LORBIT'] = parameters.lorbit

            prepare_vasp_inputs(
                structure=structure,
                pp_path=pp_path,
                kspacing=parameters.kspacing,
                incar_dict=input_params,
                incar_params=parameters.parameters,
            )
        case _:
            raise NotImplementedError(
                f"Software {software} is not supported for SCF input preparation yet."
            )


def _validate_scf_output():
    """Validate SCF calculation completed successfully.

    Checks for 'Total CPU' in OUTCAR, following the convention from
    the legacy vaspscf script.

    Raises
    ------
    RuntimeError
        If OUTCAR is missing or calculation did not complete.
    """
    if not os.path.isfile('OUTCAR'):
        raise RuntimeError("SCF calculation failed: OUTCAR not found.")

    with open('OUTCAR', 'r') as f:
        content = f.read()

    if 'Total CPU' not in content:
        raise RuntimeError(
            "SCF calculation failed: OUTCAR does not contain 'Total CPU' marker. "
            "The calculation may not have completed successfully."
        )


def _extract_band_edges(
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
    data_lines = [line for line in OUTCAR[start:end]
                  if not re.search('[a-zA-Z]', line)]

    # Select bands for the specified spin and k-point
    offset = ((whichS - 1) * NKPTS + (whichK - 1)) * NBANDS
    band_lines = data_lines[offset:offset + NBANDS]

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

    data_lines = [line for line in OUTCAR[start:end]
                  if not re.search('[a-zA-Z]', line)]

    # Extract energies for selected spin and k-point
    offset = ((whichS - 1) * NKPTS + (whichK - 1)) * NBANDS
    band_lines = data_lines[offset:offset + NBANDS]

    eigenvalues = np.array([float(line.split()[1]) for line in band_lines])

    return eigenvalues


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
    # Collect eigenvalues from all frames (directories are already in order)
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
