import os
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import ase.io
from ase import Atoms
from jobflow import job

from ..input import NVEInputT
from ..params import params_default, md_tracks
from ..input_prepare import prepare_vasp_inputs
from ..output_postprocess import (
    extract_md_data_from_oszicar,
    check_scf_convergence,
    save_md_data,
    plot_md_results,
)
from .run_software import run_software


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

    # if prepare_input_only:
    #     return {
    #         'run_dir': str(Path.cwd()),
    #         'software': software,
    #         'images': [],
    #         'strus': [],
    #         'contcar': structure,
    #     }

    # Run the software
    run_software(software_lower, nprocs)

    # Process output and check convergence
    scf_converged, md_file, images = _process_nve_output(
        software=software_lower,
        md_dt=parameters.md_dt,
        plot=plot,
    )

    if not scf_converged:
        raise RuntimeError(
            "NVE calculation failed: SCF did not converge properly in the "
            "last portion of the trajectory. Please check the output files."
        )

    if os.path.isfile(md_tracks[software_lower]):
        track = read_strus(software_lower)
        track_list = [track[i].todict() for i in range(len(track))]
    else:
        raise FileNotFoundError(f"MD track file not found for {software_lower}.")

    return {
        'run_dir': str(Path.cwd()),
        'software': software,
        'md_files': md_file,
        'images': images,
        'strus': track_list,
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

    input = deepcopy(params_default['nve'][software])
    match software:
        case 'vasp':
            input['POTIM'] = parameters.md_dt
            input['NSW'] = parameters.md_step
            input['EDIFF'] = parameters.scf_thr

            prepare_vasp_inputs(
                structure=structure,
                pp_path=pp_path,
                kspacing=parameters.kspacing,
                incar_dict=input,
                incar_params=parameters.parameters,
            )
        case _:
            raise NotImplementedError(
                f"Software {software} is not supported for NVE input preparation yet."
            )


def _process_nve_output(
    software: str,
    md_dt: float,
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
    md_dt : float
        MD time step in fs (used for saving MD data).
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
        converged_list=md_data['converged'],
        check_nsw=None,  # default: last 10% of steps
        max_unconverged_ratio=0.01,
    )

    # Save MD data
    md_file = save_md_data(md_data, md_dt, filename='md_nve.dat')

    # Generate plots if requested
    images = []
    if plot:
        image = plot_md_results(md_data, filename='nve_results.png')
        images.append(image)

    return scf_converged, md_file, images


def read_strus(software: str) -> List[Atoms]:
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
            structure = ase.io.read('XDATCAR', format='vasp-xdatcar', index=':')
        case _:
            raise ValueError(f"Unsupported software: {software}")

    return structure
