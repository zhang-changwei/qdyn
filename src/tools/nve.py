import os
import re
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import ase.io
import matplotlib

matplotlib.use('agg')
import matplotlib.pyplot as plt
import numpy as np
from ase import Atoms
from jobflow import job

from ..input import NVEInputT
from ..params import params_default
from ..input_prepare import prepare_vasp_inputs
from ..output_postprocess import extract_md_data_from_oszicar
from .run_vasp import run_vasp
from .nvt import check_scf_convergence, save_md_data


@job
def run_nve(
    software: str,
    parameters: NVEInputT,
    pp_path: str,
    orb_path: str,
    structure: Atoms,
    nodes: int = 1,
    ntasks_per_node: int = 1,
    cpus_per_task: int = 1,
    plot: bool = False,
    prepare_input_only: bool = False,
) -> Dict:
    """Run NVE molecular dynamics simulation.

    Jobflow automatically manages the working directory, so all input files
    are written to the current directory.

    Parameters
    ----------
    software : str
        Software name ('vasp', 'cp2k', etc.).
    parameters : NVEInputT
        NVE simulation parameters.
    pp_path : str
        Path to pseudopotential files.
    orb_path : str
        Path to orbital files (for SIESTA/ABACUS/OpenMX).
    structure : Atoms
        Atomic structure (typically CONTCAR from NVT).
    nodes : int
        Number of nodes for parallel calculation.
    ntasks_per_node : int
        Number of MPI tasks per node.
    cpus_per_task : int
        Number of CPUs per task.
    plot : bool
        Whether to generate plots.
    prepare_input_only : bool
        If True, only prepare input files without running the calculation.

    Returns
    -------
    Dict
        Dictionary containing:
        - run_dir: Current working directory path
        - software: Software name used
        - images: List of paths to generated plot files
        - strus: List of Atoms structures extracted from XDATCAR
        - contcar: Final atomic structure (from CONTCAR)

    Raises
    ------
    RuntimeError
        If SCF convergence fails in the last portion of the trajectory.
    """

    software_lower = software.lower()
    nprocs = nodes * ntasks_per_node

    # Prepare input files
    _prepare_nve_input(
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
            'images': [],
            'strus': [],
            'contcar': structure,
        }

    # Run VASP
    run_vasp(nprocs=nprocs)

    # Process output and check convergence
    scf_converged, md_file, images = _process_nve_output(
        software=software_lower,
        parameters=parameters,
        plot=plot,
    )

    if not scf_converged:
        raise RuntimeError(
            "NVE calculation failed: SCF did not converge properly in the "
            "last portion of the trajectory. Please check the output files."
        )

    # Read structures from XDATCAR for subsequent SCF calculations
    strus = _read_xdatcar_structures()

    # Read final structure
    contcar = structure
    if os.path.isfile('CONTCAR'):
        contcar = ase.io.read('CONTCAR', format='vasp')

    return {
        'run_dir': str(Path.cwd()),
        'software': software,
        'md_files': [md_file],
        'images': images,
        'strus': strus,
        'contcar': contcar,
    }


def _prepare_nve_input(
    software: str,
    structure: Atoms,
    parameters: NVEInputT,
    pp_path: str,
    orb_path: str,
):
    """Prepare input files for NVE molecular dynamics.

    Parameters
    ----------
    software : str
        Software name ('vasp', etc.).
    structure : Atoms
        Atomic structure.
    parameters : NVEInputT
        NVE parameters.
    pp_path : str
        Path to pseudopotential directory.
    orb_path : str
        Path to orbital files.
    """

    input_params = deepcopy(params_default['nve'][software])
    match software:
        case 'vasp':
            input_params['SMASS'] = parameters.smass
            input_params['POTIM'] = parameters.potim
            input_params['NSW'] = parameters.nsw
            input_params['NBLOCK'] = parameters.nblock
            input_params['EDIFF'] = parameters.scf_thr
            input_params['ALGO'] = parameters.algo
            input_params['NELM'] = parameters.nelm
            input_params['NELMIN'] = parameters.nelmin
            input_params['IBRION'] = parameters.ibrion
            input_params['ISYM'] = parameters.isym
            prepare_vasp_inputs(
                structure=structure,
                pp_path=pp_path,
                kspacing=parameters.kspacing,
                incar_dict=input_params,
                incar_params=parameters.parameters,
            )
        case _:
            raise NotImplementedError(
                f"Software {software} is not supported for NVE input preparation yet."
            )


def _process_nve_output(
    software: str,
    parameters: NVEInputT,
    plot: bool,
) -> Tuple[bool, str, List[str]]:
    """Process NVE output files and check convergence.

    In the old workflow, NVE convergence check uses:
    - check_nsw = wavecar_steps + 100 (last portion of trajectory needed for SCF)
    - max_unconverged = nsw // 100

    Here we check convergence of the last 10% of steps with a strict threshold.

    Parameters
    ----------
    software : str
        Software name.
    parameters : NVEInputT
        NVE parameters (used to determine check range).
    plot : bool
        Whether to generate plots.

    Returns
    -------
    Tuple[bool, str, List[str]]
        (scf_converged, md_file, images)
    """

    match software:
        case 'vasp':
            md_data = extract_md_data_from_oszicar()
        case _:
            raise NotImplementedError(
                f"MD data extraction for {software} is not implemented yet."
            )

    if md_data is None or len(md_data['steps']) == 0:
        raise FileNotFoundError(
            "Failed to extract MD data from output files. "
            "Please check the output for errors."
        )

    # Check SCF convergence on the last portion of the trajectory
    # In old workflow: check_nsw = wavecar_steps + 100, max_unconverged = nsw // 100
    # Here we check the last 10% of steps with 1% unconverged tolerance
    scf_converged = check_scf_convergence(
        md_data=md_data,
        check_nsw=None,  # default: last 10% of steps
        max_unconverged_ratio=0.01,
    )

    # Save MD data
    md_file = save_md_data(md_data, filename='md_nve.dat')

    # Generate plots if requested
    images = []
    if plot:
        image = plot_nve_results(md_data, filename='nve_results.png')
        images.append(image)

    return scf_converged, md_file, images


def _read_xdatcar_structures() -> List[Atoms]:
    """Read all structures from XDATCAR file.

    Returns
    -------
    List[Atoms]
        List of ASE Atoms objects from XDATCAR.
    """
    if not os.path.isfile('XDATCAR'):
        raise FileNotFoundError("XDATCAR file not found after NVE calculation.")

    structures = ase.io.read('XDATCAR', format='vasp-xdatcar', index=':')
    return structures


def plot_nve_results(
    md_data: Dict,
    filename: str = 'nve_results.png',
) -> str:
    """Plot NVE simulation results (temperature, potential energy, total energy).

    Parameters
    ----------
    md_data : dict
        MD data dictionary from extract_md_data_from_oszicar().
    filename : str
        Output filename for the plot.

    Returns
    -------
    str
        Path to the saved plot.
    """
    steps = md_data['steps']
    temperatures = md_data['temperatures']
    total_energies = md_data['total_energies']
    potential_energies = md_data['potential_energies']

    fig, axes = plt.subplots(3, 1, figsize=(8, 10))

    # Plot temperature
    ax1 = axes[0]
    ax1.plot(steps, temperatures, color='tab:red', linewidth=0.8)
    ax1.set_xlabel('Step')
    ax1.set_ylabel('Temperature (K)')
    ax1.set_title('Temperature Evolution (NVE)')

    # Plot potential energy
    ax2 = axes[1]
    ax2.plot(steps, potential_energies, color='tab:green', linewidth=0.8)
    ax2.set_xlabel('Step')
    ax2.set_ylabel('Potential Energy (eV)')
    ax2.set_title('Potential Energy Evolution (NVE)')

    # Plot total energy (should be conserved in NVE)
    ax3 = axes[2]
    ax3.plot(steps, total_energies, color='tab:blue', linewidth=0.8)
    ax3.set_xlabel('Step')
    ax3.set_ylabel('Total Energy (eV)')
    ax3.set_title('Total Energy Conservation (NVE)')

    fig.tight_layout()
    plt.savefig(filename, dpi=300)
    plt.close()

    return os.path.abspath(filename)
