import os
import shutil
import subprocess
from typing import Dict, Literal, Optional, Tuple
from copy import deepcopy

import ase.io
import matplotlib

matplotlib.use('agg')
import matplotlib.pyplot as plt
import numpy as np
from ase import Atoms
from pymatgen.io.vasp import Incar
from jobflow import job

from ..input import NVTInputT
from ..params import params_default
from ..input_prepare import prepare_vasp_inputs
from ..output_postprocess import extract_md_data_from_oszicar
from ..output import Output


MAX_NVT_RETRIES = 10  # Maximum number of NVT retries for temperature convergence


@job
def run_nvt(
    software: str,
    parameters: NVTInputT,
    pp_path: str,
    orb_path: str,
    structure: Atoms,
    nodes: int = 1,
    ntasks_per_node: int = 1,
    cpus_per_task: int = 1,
    plot: bool = False,
    prepare_input_only: bool = False,
) -> Output:
    """Run NVT molecular dynamics simulation with automatic retry on temperature divergence.

    Jobflow automatically manages the working directory, so all input files
    are written to the current directory.

    If temperature does not converge within 10% of target temperature, the
    simulation will be restarted using CONTCAR as the new structure, up to
    MAX_NVT_RETRIES times.

    Parameters
    ----------
    software : str
        Software name ('vasp', 'cp2k', etc.).
    parameters : NVTInputT
        NVT simulation parameters.
    pp_path : str
        Path to pseudopotential files.
    orb_path : str
        Path to orbital files (for SIESTA/ABACUS/OpenMX).
    structure : Atoms
        Atomic structure.
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
    Output
        Output object containing files and images.

    Raises
    ------
    RuntimeError
        If SCF convergence fails or temperature does not converge after
        MAX_NVT_RETRIES attempts.
    """
    output = Output()
    software_lower = software.lower()

    current_structure = structure
    nprocs = nodes * ntasks_per_node

    for attempt in range(1, MAX_NVT_RETRIES + 1):
        output.stdout.append(f"\n{'=' * 50}")
        output.stdout.append(f"NVT Attempt {attempt}/{MAX_NVT_RETRIES}")
        output.stdout.append(f"{'=' * 50}")

        # Prepare input files
        _prepare_nvt_input(
            software=software_lower,
            structure=current_structure,
            parameters=parameters,
            pp_path=pp_path,
            orb_path=orb_path,
        )

        # Run VASP
        result = subprocess.run(
            ['mpirun', '-np', str(nprocs), 'vasp'],
            capture_output=True,
            text=True,
        )

        # Process output and check convergence
        scf_converged, temp_converged, avg_temp, max_deviation = _process_nvt_output(
            software=software_lower,
            target_temp=parameters.temp_end,
            plot=plot,
            output=output,
            attempt=attempt,
        )

        # Check 1: SCF convergence - if failed, raise error immediately
        if not scf_converged:
            error_msg = (
                f"NVT calculation failed: SCF did not converge properly. "
                f"Please check the output files for details."
            )
            output.stdout.append(f"ERROR: {error_msg}")
            raise RuntimeError(error_msg)

        # Check 2: Temperature convergence
        if temp_converged:
            output.stdout.append(
                f"NVT simulation completed successfully after {attempt} attempt(s)."
            )
            output.stdout.append(f"Final average temperature: {avg_temp:.1f} K")
            output.stdout.append(f"Max temperature deviation: {max_deviation:.1f} K")
            break
        else:
            output.stdout.append(
                f"Temperature not converged (deviation: {max_deviation:.1f} K > "
                f"{parameters.temp_end * 0.10:.1f} K). "
                f"Will restart from CONTCAR..."
            )

            # Check if we've exhausted retries
            if attempt >= MAX_NVT_RETRIES:
                error_msg = (
                    f"NVT calculation failed: Temperature did not converge after "
                    f"{MAX_NVT_RETRIES} attempts. Max deviation: {max_deviation:.1f} K. "
                    f"Please check the system or increase MAX_NVT_RETRIES."
                )
                output.stdout.append(f"ERROR: {error_msg}")
                raise RuntimeError(error_msg)

            # Read CONTCAR for next iteration
            if not os.path.isfile('CONTCAR'):
                error_msg = "CONTCAR not found after NVT calculation."
                output.stdout.append(f"ERROR: {error_msg}")
                raise RuntimeError(error_msg)

            # Backup current round files
            backup_dir = f"nvt_attempt_{attempt}"
            os.makedirs(backup_dir, exist_ok=True)
            for f in [
                'POSCAR',
                'CONTCAR',
                'OSZICAR',
                'OUTCAR',
                'INCAR',
                'KPOINTS',
                'POTCAR',
            ]:
                if os.path.isfile(f):
                    shutil.copy(f, os.path.join(backup_dir, f))
            if os.path.isfile(f'nvt_results_attempt_{attempt}.png'):
                shutil.move(
                    f'nvt_results_attempt_{attempt}.png',
                    os.path.join(backup_dir, f'nvt_results_attempt_{attempt}.png'),
                )
            if os.path.isfile(f'md_attempt_{attempt}.dat'):
                shutil.move(
                    f'md_attempt_{attempt}.dat',
                    os.path.join(backup_dir, f'md_attempt_{attempt}.dat'),
                )
            output.stdout.append(f"Backup files saved to {backup_dir}/")

            # Read CONTCAR as new structure for next iteration
            current_structure = ase.io.read('CONTCAR', format='vasp')
            output.stdout.append("Loaded structure from CONTCAR for next iteration.")

    return output


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

    Parameters
    ----------
    software : str
        Software name ('vasp', etc.).
    structure : Atoms
        Atomic structure.
    parameters : NVTInputT
        NVT parameters including kspacing, encut, temperature range, etc.
    pp_path : str
        Path to pseudopotential directory.
    orb_path : str
        Path to orbital files (for SIESTA/ABACUS/OpenMX).
    """

    input = deepcopy(params_default['nvt'][software])
    match software:
        case 'vasp':
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
            prepare_vasp_inputs(
                structure=structure,
                pp_path=pp_path,
                kspacing=parameters.kspacing,
                incar_dict=input,
                incar_params=parameters.parameters,
            )
        case _:
            raise NotImplementedError(
                f"Software {software} is not supported for NVT input preparation yet."
            )


def _process_nvt_output(
    software: str,
    target_temp: float,
    plot: bool,
    output: Output,
    attempt: int = 1,
    check_nsw: Optional[int] = None,
    max_unconverged_ratio: float = 0.01,
) -> Tuple[bool, bool, float, float]:
    """Process NVT output files and check convergence (universal for all software).

    This function extracts MD data using software-specific functions,
    checks SCF convergence and temperature convergence using universal
    functions, and optionally generates plots.

    Parameters
    ----------
    software : str
        Software name ('vasp', 'cp2k', etc.).
    target_temp : float
        Target temperature for NVT simulation.
    plot : bool
        Whether to generate plots.
    output : Output
        Output object to store results.
    attempt : int
        Current attempt number (for labeling).
    check_nsw : int, optional
        Number of steps to check for SCF convergence. If None, check last 5% of steps.
    max_unconverged_ratio : float
        Maximum ratio of unconverged steps allowed (default: 0.1 = 10%).

    Returns
    -------
    Tuple[bool, bool, float, float]
        (scf_converged, temp_converged, avg_temp, max_deviation)
        - scf_converged: True if SCF converged properly
        - temp_converged: True if temperature converged to target
        - avg_temp: Average temperature of last 1000 steps
        - max_deviation: Maximum temperature deviation from target
    """
    # Extract MD data using software-specific function
    match software:
        case 'vasp':
            md_data = extract_md_data_from_oszicar()
        case _:
            raise NotImplementedError(
                f"MD data extraction for {software} is not implemented yet."
            )

    if md_data is None or len(md_data['steps']) == 0:
        output.stdout.append(f"ERROR: No MD data found for {software}")
        return False, False, 0.0, float('inf')

    n_steps = len(md_data['steps'])
    output.stdout.append(f"MD steps completed: {n_steps}")

    # Check SCF convergence (universal)
    scf_converged, n_unconverged, n_checked = check_scf_convergence(
        md_data=md_data,
        check_nsw=check_nsw,
        max_unconverged_ratio=max_unconverged_ratio,
    )

    if scf_converged:
        output.stdout.append(f"SCF convergence: PASSED")
    else:
        output.stdout.append(
            f"SCF convergence: FAILED ({n_unconverged}/{n_checked} unconverged steps)"
        )

    # Check temperature convergence (universal)
    n_last = min(len(md_data['temperatures']), 1000)
    temp_converged, avg_temp, max_deviation, threshold = check_temperature_convergence(
        md_data=md_data,
        target_temp=target_temp,
        n_last=n_last,
        threshold_ratio=0.10,
    )
    output.stdout.append(f"Average temperature (last {n_last} steps): {avg_temp:.1f} K")
    output.stdout.append(f"Max temperature deviation: {max_deviation:.1f} K")

    if temp_converged:
        output.stdout.append(f"Temperature convergence: PASSED")
    else:
        output.stdout.append(
            f"Temperature convergence: FAILED "
            f"(deviation {max_deviation:.1f} K > threshold {threshold:.1f} K)"
        )

    # Save MD data to file in unified format
    md_filename = f'md_attempt_{attempt}.dat'
    md_data_path = save_md_data(md_data, filename=md_filename)
    output.files.append(md_data_path)

    # Generate plots if requested
    if plot:
        plot_filename = f'nvt_results_attempt_{attempt}.png'
        plot_path = plot_nvt_results(md_data, target_temp, filename=plot_filename)
        output.images.append(plot_path)

    return scf_converged, temp_converged, avg_temp, max_deviation


def check_scf_convergence(
    md_data: Dict,
    check_nsw: Optional[int] = None,
    max_unconverged_ratio: float = 0.01,
) -> Tuple[bool, int, int]:
    """Check SCF convergence from MD data (universal for all software).

    This function checks if SCF converged properly based on the converged
    flags in the MD data.

    Parameters
    ----------
    md_data : dict
        MD data dictionary with 'converged' field.
    check_nsw : int, optional
        Number of steps to check (from the end). If None, check last 5% of steps.
    max_unconverged_ratio : float
        Maximum ratio of unconverged steps allowed (default: 0.01 = 1%).

    Returns
    -------
    Tuple[bool, int, int]
        (converged, n_unconverged, n_total)
        - converged: True if SCF converged properly
        - n_unconverged: Number of unconverged steps
        - n_total: Total number of steps checked
    """
    converged_list = md_data['converged']
    n_steps = len(converged_list)

    if n_steps == 0:
        return False, 0, 0

    # Default: check last 5% of steps
    if check_nsw is None:
        check_nsw = n_steps // 10

    # Get the range to check
    check_range = converged_list[-check_nsw:]

    n_total = len(check_range)
    n_unconverged = sum(1 for c in check_range if not c)
    max_unconverged = int(check_nsw * max_unconverged_ratio)

    # Converged if unconverged steps in check range <= max_unconverged
    converged = n_unconverged <= max_unconverged

    return converged, n_unconverged, n_total


def check_temperature_convergence(
    md_data: Dict,
    target_temp: float,
    n_last: int = 1000,
    threshold_ratio: float = 0.10,
) -> Tuple[bool, float, float, float]:
    """Check temperature convergence from MD data (universal for all software).

    This function checks if temperature converged to the target value.

    Parameters
    ----------
    md_data : dict
        MD data dictionary with 'temperatures' field.
    target_temp : float
        Target temperature for NVT simulation.
    n_last : int
        Number of last steps to use for averaging (default: 1000).
    threshold_ratio : float
        Maximum allowed deviation as ratio of target temp (default: 0.10 = 10%).

    Returns
    -------
    Tuple[bool, float, float]
        (converged, avg_temp, max_deviation)
        - converged: True if temperature converged to target
        - avg_temp: Average temperature of last n_last steps
        - max_deviation: Maximum temperature deviation from target
    """
    temps = np.array(md_data['temperatures'])
    n_steps = len(temps)

    if n_steps == 0:
        return False, 0.0, float('inf'), 0.0

    # Use last n_last steps (or all if fewer)
    n_check = min(n_steps, n_last)
    last_ntemps = temps[-n_check:]

    avg_temp = np.mean(last_ntemps)
    temp_deviation = np.abs(last_ntemps - target_temp)
    max_deviation = np.max(temp_deviation)

    # Check if max deviation is within threshold
    threshold = target_temp * threshold_ratio
    converged = max_deviation <= threshold

    return converged, avg_temp, max_deviation, threshold


def plot_nvt_results(
    md_data: Dict,
    target_temp: float,
    filename: str = 'nvt_results.png',
) -> str:
    """Plot NVT simulation results.

    Parameters
    ----------
    md_data : dict
        MD data dictionary from extract_md_data_from_oszicar().
    target_temp : float
        Target temperature for reference line.
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
    ax1.axhline(
        y=target_temp,
        color='gray',
        linestyle='--',
        linewidth=1,
        label=f'Target: {target_temp} K',
    )
    ax1.set_xlabel('Step')
    ax1.set_ylabel('Temperature (K)')
    ax1.legend(loc='upper right')
    ax1.set_title('Temperature Evolution')

    # Plot potential energy
    ax2 = axes[1]
    ax2.plot(steps, potential_energies, color='tab:green', linewidth=0.8)
    ax2.set_xlabel('Step')
    ax2.set_ylabel('Potential Energy (eV)')
    ax2.set_title('Potential Energy Evolution')

    # Plot total energy
    ax3 = axes[2]
    ax3.plot(steps, total_energies, color='tab:blue', linewidth=0.8)
    ax3.set_xlabel('Step')
    ax3.set_ylabel('Total Energy (eV)')
    ax3.set_title('Total Energy Evolution')

    fig.tight_layout()
    plt.savefig(filename, dpi=300)
    plt.close()

    return os.path.abspath(filename)


def save_md_data(md_data: Dict, filename: str = 'md.dat') -> str:
    """Save MD data to a file in unified format.

    This function saves MD data in a unified format that works for all
    supported software (VASP, CP2K, SIESTA, ABACUS, OpenMX, etc.).

    Parameters
    ----------
    md_data : dict
        MD data dictionary with unified format:
        - 'steps': list of step numbers
        - 'temperatures': list of temperatures (K)
        - 'total_energies': list of total energies (eV)
        - 'potential_energies': list of potential energies (eV)
        - 'kinetic_energies': list of kinetic energies (eV)
        - 'converged': list of bool, SCF convergence status for each step
        - 'potim': time step (fs)
    filename : str
        Output filename (default: 'md.dat').

    Returns
    -------
    str
        Path to the saved file.
    """
    with open(filename, 'w') as f:
        f.write(f"# Time step (fs): {md_data['potim']}\n")
        f.write(
            "# Step  Temperature(K)  Total_Energy(eV)  E_pot(eV)  E_kin(eV)  Converged\n"
        )

        for i in range(len(md_data['steps'])):
            conv_flag = 1 if md_data['converged'][i] else 0
            f.write(
                f"{md_data['steps'][i]:6d} "
                f"{md_data['temperatures'][i]:12.2f} "
                f"{md_data['total_energies'][i]:16.8f} "
                f"{md_data['potential_energies'][i]:14.8f} "
                f"{md_data['kinetic_energies'][i]:14.8f} "
                f"{conv_flag}\n"
            )

        # Summary lines
        temps = np.array(md_data['temperatures'])
        converged_list = md_data['converged']
        n_converged = sum(converged_list)
        n_total = len(converged_list)

        f.write(f"# Total steps: {n_total}\n")
        f.write(f"# Converged steps: {n_converged}/{n_total}\n")
        f.write(f"# Average T (K): {np.mean(temps):.2f}\n")

    return os.path.abspath(filename)
