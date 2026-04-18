import os
import shutil
import logging
from pathlib import Path
from typing import Dict, Literal, Tuple, NamedTuple
from copy import deepcopy

import ase.io
import numpy as np


from ase import Atoms, geometry
from jobflow import job  # type: ignore

from ..input import NVTInputT
from ..params import params_default, backup_files
from ..input_prepare import DFTInputs
from ..output_postprocess import (
    extract_md_data_from_oszicar,
    check_scf_convergence,
    save_md_data,
    plot_md_results,
)
from .run_software import run_software


MAX_NVT_RETRIES = 10  # Maximum number of NVT retries for temperature convergence


class NVTOutputT(NamedTuple):
    current_structure: Atoms
    scf_converged: bool
    temp_converged: bool
    max_deviation: float
    md_file: str
    image: str


@job
def qdyn_nvt(
    software: str,
    parameters: NVTInputT,
    pp_path: str,
    orb_path: str,
    structure: Dict,
    nodes: int = 1,
    processes_per_node: int = 1,
    threads_per_process: int = 1,
    plot: bool = False,
    prepare_input_only: bool = False,
) -> Dict:
    """Run NVT molecular dynamics simulation with automatic retry on temperature divergence.

    Jobflow automatically manages the working directory, so all input files
    are written to the current directory.

    If temperature does not converge within 10% of target temperature, the
    simulation will be restarted using CONTCAR as the new structure, up to
    MAX_NVT_RETRIES times.

    Args:
        software: Software name ('vasp', 'cp2k', etc.).
        parameters: NVT simulation parameters.
        pp_path: Path to pseudopotential files.
        orb_path: Path to orbital files (for SIESTA/ABACUS/OpenMX).
        structure: Atomic structure.
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
        - contcar: Final atomic structure (from CONTCAR)

    Raises:
        RuntimeError: If SCF convergence fails or temperature does not
            converge after MAX_NVT_RETRIES attempts.
    """

    software_lower = software.lower()

    structure.pop('momenta', None)
    current_structure = Atoms.fromdict(structure)
    if (
        parameters.constraint_layers is not None
        and current_structure.constraints is None
    ):
        current_structure = add_constraints(
            current_structure,
            parameters.constraint_layers,
            parameters.layer_direction,  # type: ignore
            parameters.total_layers,  # type: ignore
        )

    nprocs = nodes * processes_per_node
    images = []
    md_files = []

    for attempt in range(1, MAX_NVT_RETRIES + 1):

        # Prepare input files
        _prepare_nvt_input(
            software=software_lower,
            structure=current_structure,
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
                'stru': [],
            }

        # Run the software
        run_software(software_lower, nprocs)

        # Process output and check convergence
        (
            current_structure,
            scf_converged,
            temp_converged,
            max_deviation,
            attempt_mdfile,
            attempt_image,
        ) = _process_nvt_output(
            software=software_lower,
            target_temp=parameters.temp_end,
            md_dt=parameters.md_dt,
            plot=plot,
            attempt=attempt,
        )
        md_files.append(attempt_mdfile)
        images.append(attempt_image)

        # Check 1: SCF convergence - if failed, raise error immediately
        if not scf_converged:
            error_msg = (
                f"NVT calculation failed: SCF did not converge properly. "
                f"Please check the output files for details."
            )
            raise RuntimeError(error_msg)

        # Check 2: Temperature convergence
        if temp_converged:
            break
        else:
            # Check if we've exhausted retries
            if attempt >= MAX_NVT_RETRIES:
                error_msg = (
                    f"NVT calculation failed: Temperature did not converge after "
                    f"{MAX_NVT_RETRIES} attempts. Max deviation: {max_deviation:.1f} K. "
                    f"Please check the system or increase MAX_NVT_RETRIES."
                )
                raise RuntimeError(error_msg)

            # Read CONTCAR for next iteration
            if not os.path.isfile('CONTCAR'):
                error_msg = "CONTCAR not found after NVT calculation."
                raise RuntimeError(error_msg)

            # Backup current round files
            backup_dir = f"nvt_attempt_{attempt}"
            md_filename = f'md_attempt_{attempt}.dat'
            image_filename = f'nvt_results_attempt_{attempt}.png'
            os.makedirs(backup_dir, exist_ok=True)
            for f in backup_files[software_lower]:
                if os.path.isfile(f):
                    shutil.copy(f, os.path.join(backup_dir, f))
                else:
                    logging.warning(
                        f'File {f} not found, backup files may be uncomplete.'
                    )
            if os.path.isfile(md_filename):
                md_dstpath = os.path.join(backup_dir, md_filename)
                shutil.move(md_filename, md_dstpath)
                md_files[attempt - 1] = os.path.abspath(md_dstpath)
            else:
                logging.warning(
                    f'File {md_filename} not found, backup files may be uncomplete.'
                )
            if os.path.isfile(image_filename):
                image_dstpath = os.path.join(backup_dir, image_filename)
                shutil.move(
                    image_filename,
                    image_dstpath,
                )
                images[attempt - 1] = os.path.abspath(image_dstpath)
            else:
                logging.warning(
                    f'File {image_filename} not found, backup files may be uncomplete.'
                )

    stru_dict = current_structure.todict()
    if stru_dict.get('constraints') is not None:
        stru_dict['constraints'] = [i.todict() for i in stru_dict['constraints']]  # type: ignore

    return {
        'run_dir': str(Path.cwd()),
        'software': software,
        'md_files': md_files,
        'images': images,
        'stru': stru_dict,
    }


def _prepare_nvt_input(
    software: str,
    structure: Atoms,
    parameters: NVTInputT,
    pp_path: str,
    orb_path: str,
):
    """Prepare input files for NVT molecular dynamics.

    This function prepares input files (POSCAR, KPOINTS, POTCAR, INCAR for VASP)
    for an NVT molecular dynamics calculation in the current directory.

    Args:
        software: Software name ('vasp', etc.).
        structure: Atomic structure.
        parameters: NVT parameters including kspacing, encut, temperature
            range, etc.
        pp_path: Path to pseudopotential directory.
        orb_path: Path to orbital files (for SIESTA/ABACUS/OpenMX).
    """

    input = deepcopy(params_default['nvt'][software])
    if software == 'vasp':
        # Handle predefined parameters in InputT
        # 检查这些参数！！！！！
        if parameters.md_thermostat == 'nhc':
            input['MDALGO'] = 2
            # input['ISIF'] = 0
            input['SMASS'] = 0
        elif parameters.md_thermostat == 'rescale_v':
            input['MDALGO'] = 0
            # input['ISIF'] = 0
            input['SMASS'] = -1
            input['NBLOCK'] = 4
        input['POTIM'] = parameters.md_dt
        input['NSW'] = parameters.md_step
        input['TEBEG'] = parameters.temp_begin
        input['TEEND'] = parameters.temp_end
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
            f"Software {software} is not supported for NVT input preparation yet."
        )


def _process_nvt_output(
    software: str,
    target_temp: float,
    md_dt: float,
    plot: bool,
    attempt: int = 1,
    check_nsw: int | None = None,
    max_unconverged_ratio: float = 0.01,
) -> NVTOutputT:
    """Process NVT output files and check convergence (universal for all software).

    This function extracts MD data using software-specific functions,
    checks SCF convergence and temperature convergence using universal
    functions, and optionally generates plots.

    Args:
        software: Software name ('vasp', 'cp2k', etc.).
        target_temp: Target temperature for NVT simulation.
        plot: Whether to generate plots.
        attempt: Current attempt number (for labeling).
        check_nsw: Number of steps to check for SCF convergence. If None,
            check last 5% of steps.
        max_unconverged_ratio: Maximum ratio of unconverged steps allowed
            (default: 0.1 = 10%).

    Returns:
        (current_structure, scf_converged, temp_converged, max_deviation, image, md_file)
        - current_structure: The updated atomic structure
        - scf_converged: True if SCF converged properly
        - temp_converged: True if temperature converged to target
        - max_deviation: Maximum temperature deviation from target
        - md_file: Path to saved MD data file
        - image: Path to generated plot file
    """

    # Extract MD data using software-specific function
    if software == 'vasp':
        md_data = extract_md_data_from_oszicar()
        # Read CONTCAR as new structure for next iteration
        current_structure = ase.io.read('CONTCAR', format='vasp')  # type: ignore
    else:
        raise NotImplementedError(
            f"MD data extraction for {software} is not implemented yet."
        )

    if md_data is None or len(md_data['steps']) == 0:
        raise FileNotFoundError(
            "Failed to extract MD data from output files. Please check the output for errors."
        )

    # Check SCF convergence (universal)
    scf_converged = check_scf_convergence(
        converged_list=md_data['converged'],
        check_nsw=check_nsw,
        max_unconverged_ratio=max_unconverged_ratio,
    )

    # Check temperature convergence (universal)
    n_last = min(len(md_data['temperatures']), 1000)
    temp_converged, max_deviation = check_temperature_convergence(
        md_data=md_data,
        target_temp=target_temp,
        n_last=n_last,
        threshold_ratio=0.10,
    )

    # Save MD data to file in unified format
    md_filename = f'md_attempt_{attempt}.dat'
    md_file = save_md_data(md_data, md_dt, filename=md_filename)

    image = ''
    # Generate plots if requested
    if plot:
        plot_filename = f'nvt_results_attempt_{attempt}.png'
        image = plot_md_results(md_data, plot_filename, target_temp)

    return NVTOutputT(
        current_structure,  # type: ignore
        scf_converged,
        temp_converged,
        max_deviation,
        md_file,
        image,
    )


def add_constraints(
    structure: Atoms,
    constraint_layers: str,
    layer_direction: Literal['000', '001', '010', '011', '100', '101', '110', '111'],
    total_layers: int,
) -> Atoms:
    """Add layer-based constraints to the structure.

    Parameters
    ----------
    structure : Atoms
        ASE Atoms object representing the structure.
    constraint_layers : int
        Number of layers to constrain (starting from the bottom).
    layer_direction : str
        Miller indices of the crystal surface.
    total_layers : int
        Total number of layers in the structure.
    """
    from ase.constraints import FixAtoms

    # Get layer indices based on geometry
    miller = np.array(list(layer_direction), dtype=int)

    _, layers = auto_tolerance(structure, miller, total_layers)

    clayers = []
    for part in constraint_layers.split():
        if '-' in part:
            start, end = map(int, part.split('-'))
            clayers.extend(range(start - 1, end))
        else:
            clayers.append(int(part) - 1)

    mask = np.isin(layers[0], clayers)
    c = FixAtoms(mask=mask)
    structure.set_constraint(c)  # type: ignore
    return structure


def auto_tolerance(
    structure: Atoms,
    miller: np.ndarray,
    target: int,
    low: float = 0.01,
    high: float = 10,
    max_iter: int = 30,
) -> Tuple[float, tuple]:

    for _ in range(max_iter):
        mid = (low + high) / 2
        layers = geometry.get_layers(structure, miller, tolerance=mid)
        n = len(layers[1])
        if n == target:
            return mid, layers
        elif n > target:
            low = mid
        else:
            high = mid

    logging.warning(
        f"Can't split the structure into {target} layers within {max_iter} iterations. "
        f"Final layer distances: {mid:.4f}, layers found: {n}."
    )
    return low, geometry.get_layers(structure, miller, tolerance=low)


def check_temperature_convergence(
    md_data: Dict,
    target_temp: float,
    n_last: int = 1000,
    threshold_ratio: float = 0.10,
) -> Tuple[bool, float]:
    """Check temperature convergence from MD data (universal for all software).

    This function checks if temperature converged to the target value.

    Args:
        md_data: MD data dictionary with 'temperatures' field.
        target_temp: Target temperature for NVT simulation.
        n_last: Number of last steps to use for averaging (default: 1000).
        threshold_ratio: Maximum allowed deviation as ratio of target temp
            (default: 0.10 = 10%).

    Returns:
        (converged, avg_temp, max_deviation)
        - converged: True if temperature converged to target
        - avg_temp: Average temperature of last n_last steps
        - max_deviation: Maximum temperature deviation from target
    """
    temps = np.array(md_data['temperatures'])
    n_steps = len(temps)

    if n_steps == 0:
        raise ValueError("No temperature data available to check convergence.")

    # Use last n_last steps (or all if fewer)
    n_check = min(n_steps, n_last)
    last_ntemps = temps[-n_check:]

    temp_deviation = np.abs(last_ntemps - target_temp)
    max_deviation = np.max(temp_deviation)

    # Check if max deviation is within threshold
    threshold = target_temp * threshold_ratio
    converged = max_deviation <= threshold

    return converged, max_deviation
