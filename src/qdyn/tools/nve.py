import os
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Tuple

import ase.io
from ase import Atoms
from jobflow import job
import numpy as np


from ..input import NVEInputT
from ..params import params_default, TRAJ_FNAME_MAPPING
from ..input_prepare import DFTInputs
from ..output_postprocess import MDOutpus
from .run_software import run_software
from .seldyn import add_constraints


@job
def qdyn_nve(
    software: str,
    parameters: NVEInputT,
    pp_path: str,
    orb_path: str,
    structure: Dict,
    nodes: int = 1,
    processes_per_node: int = 1,
    threads_per_process: int = 1,
    plot: bool = False,
    prepare_input_only: bool = False,
) -> Dict:
    """Run NVE molecular dynamics simulation.

    Jobflow automatically manages the working directory, so all input files
    are written to the current directory.

    Args:
        software: Software name ('vasp', 'cp2k', etc.).
        parameters: NVE simulation parameters.
        pp_path: Path to pseudopotential files.
        orb_path: Path to orbital files (for SIESTA/ABACUS/OpenMX).
        structure: Atomic structure (typically CONTCAR from NVT).
        nodes: Number of nodes for parallel calculation.
        processes_per_node: Number of MPI tasks per node.
        threads_per_process: Number of CPUs per task.
        plot: Whether to generate plots.
        prepare_input_only: If True, only prepare input files without running
            the calculation.

    Returns:
        Dict:
        - run_dir: Current working directory path
        - software: Software name used
        - images: List of paths to generated plot files
        - strus: List of Atoms structures extracted from XDATCAR
        - contcar: Final atomic structure (from CONTCAR)

    Raises:
        RuntimeError: If SCF convergence fails in the last portion of the trajectory.
    """

    software_lower = software.lower()
    nprocs = nodes * processes_per_node

    structure['momenta'] = np.array(structure['momenta'])
    cstru = Atoms.fromdict(structure)
    if parameters.sel.constraint_layers is not None and not cstru.constraints:
        cstru = add_constraints(cstru, parameters.sel)

    # Prepare input files
    _prepare_nve_input(
        software=software_lower,
        structure=cstru,
        parameters=parameters,
        pp_path=pp_path,
        orb_path=orb_path,
    )

    if prepare_input_only:
        return {
            'run_dir': str(Path.cwd()),
            'software': software,
            'md_files': [],
            'images': [],
            'strus': [],
        }

    # Run the software
    run_software(software_lower, nprocs)

    # Process output and check convergence
    mdoutputs = _process_nve_output(
        software=software_lower,
        md_dt=parameters.md_dt,
        plot=plot,
    )

    if not mdoutputs.scf_converged:
        raise RuntimeError(
            "NVE calculation failed: SCF did not converge properly in the "
            "last portion of the trajectory. Please check the output files."
        )

    track_name = TRAJ_FNAME_MAPPING.get(software_lower)
    if track_name is None:
        raise ValueError(f"Unsupported software: {software_lower}")
    # if os.path.isfile(track_name):
    #     strus = read_strus(software_lower)
    #     strus_list = [strus[i].todict() for i in range(len(strus))]
    # else:
    #     raise FileNotFoundError(f"MD track file not found for {software_lower}.")

    return {
        'run_dir': str(Path.cwd()),
        'software': software,
        'md_files': mdoutputs.md_file,
        'images': [mdoutputs.image], # return list in previous version for consistency, but currently only one image is generated in NVE workflow.
        # 'strus': strus_list,
        'traj_path': str(
            Path.cwd() / TRAJ_FNAME_MAPPING[software_lower]
        ),  # constraints information may also remain in some software's trajectory files, may raise error when changing to dict.
    }


def _prepare_nve_input(
    software: str,
    structure: Atoms,
    parameters: NVEInputT,
    pp_path: str,
    orb_path: str,
):
    """Prepare input files for NVE molecular dynamics.

    Args:
        software: Software name ('vasp', etc.).
        structure: Atomic structure.
        parameters: NVE parameters.
        pp_path: Path to pseudopotential directory.
        orb_path: Path to orbital files.
    """

    input = deepcopy(params_default['nve'][software])
    if software == 'vasp':
        input['POTIM'] = parameters.md_dt
        input['NSW'] = parameters.md_step
        input['EDIFF'] = parameters.scf_thr

        dftinputs = DFTInputs(
            software='vasp',
            structure=structure,
            pp_path=pp_path,
            orb_path=orb_path,
            kspacing=parameters.kspacing,
            inputs_dict=input,
            inputs_params=parameters.parameters,
        )
        dftinputs.write()
    else:
        raise NotImplementedError(
            f"Software {software} is not supported for NVE input preparation yet."
        )


def _process_nve_output(
    software: str,
    md_dt: float,
    plot: bool,
) -> MDOutpus:
    """Process NVE output files and check convergence.

    In the old workflow, NVE convergence check uses:
    - check_nsw = wavecar_steps + 100 (last portion of trajectory needed for SCF)
    - max_unconverged = nsw // 100

    Here we check convergence of the last 10% of steps with a strict threshold.

    Args:
        software: Software name.
        md_dt: MD time step in fs (used for saving MD data).
        plot: Whether to generate plots.

    Returns:
        (scf_converged, md_file, images)
    """

    if software == 'vasp':
        mdoutputs = MDOutpus.from_md_tracks(software='vasp')
    else:
        raise NotImplementedError(
            f"MD data extraction for {software} is not implemented yet."
        )

    # Check SCF convergence on the last portion of the trajectory
    # In old workflow: check_nsw = wavecar_steps + 100, max_unconverged = nsw // 100
    # Here we check the last 10% of steps with 1% unconverged tolerance
    mdoutputs.check_scf_convergence(
        check_nsw=None,
        max_unconverged_ratio=0.01,
    )

    # Save MD data
    mdoutputs.save_md_data(md_dt, filename='md_nve.dat')

    # Generate plots if requested
    if plot:
        mdoutputs.plot_md_results(filename='nve_results.png')

    return mdoutputs
