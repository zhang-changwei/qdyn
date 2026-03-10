import os
import shutil
import subprocess
from typing import Dict, Literal, Optional, Tuple

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
from ..job_initialize import prepare_vasp_inputs
from ..output import Output


MAX_NVT_RETRIES = 10  # Maximum number of NVT retries for temperature convergence


@job
def run_nvt(
    structure: Atoms,
    software: str,
    parameters: NVTInputT,
    pp_path: str = '',
    orb_path: str = '',
    nodes: int = 1,
    ntasks_per_node: int = 1,
    cpus_per_task: int = 1,
    plot: bool = False,
) -> Output:
    """Run NVT molecular dynamics simulation with automatic retry on temperature divergence.

    Jobflow automatically manages the working directory, so all input files
    are written to the current directory.

    If temperature does not converge within 10% of target temperature, the
    simulation will be restarted using CONTCAR as the new structure, up to
    MAX_NVT_RETRIES times.

    Parameters
    ----------
    structure : Atoms
        Atomic structure.
    software : str
        Software name ('vasp', 'cp2k', etc.).
    parameters : NVTInputT
        NVT simulation parameters.
    pp_path : str
        Path to pseudopotential files.
    orb_path : str
        Path to orbital files (for SIESTA/ABACUS/OpenMX).
    nodes : int
        Number of nodes for parallel calculation.
    ntasks_per_node : int
        Number of MPI tasks per node.
    cpus_per_task : int
        Number of CPUs per task.
    plot : bool
        Whether to generate plots.

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

    if software_lower != 'vasp':
        raise NotImplementedError(
            f"NVT with software {software} is not implemented yet."
        )

    current_structure = structure
    nprocs = nodes * ntasks_per_node

    for attempt in range(1, MAX_NVT_RETRIES + 1):
        output.stdout.append(f"\n{'=' * 50}")
        output.stdout.append(f"NVT Attempt {attempt}/{MAX_NVT_RETRIES}")
        output.stdout.append(f"{'=' * 50}")

        # Prepare input files
        _prepare_nvt_input_vasp(
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
        scf_converged, temp_converged, avg_temp, max_deviation = _process_nvt_output_vasp(
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
            for f in ['POSCAR', 'CONTCAR', 'OSZICAR', 'OUTCAR', 'INCAR', 'KPOINTS', 'POTCAR']:
                if os.path.isfile(f):
                    shutil.copy(f, os.path.join(backup_dir, f))
            if os.path.isfile('nvt_results.png'):
                shutil.move('nvt_results.png', os.path.join(backup_dir, 'nvt_results.png'))
            if os.path.isfile('md_vasp.dat'):
                shutil.move('md_vasp.dat', os.path.join(backup_dir, 'md_vasp.dat'))
            output.stdout.append(f"Backup files saved to {backup_dir}/")

            # Read CONTCAR as new structure for next iteration
            current_structure = ase.io.read('CONTCAR', format='vasp')
            output.stdout.append("Loaded structure from CONTCAR for next iteration.")

    return output


def _prepare_nvt_input_vasp(
    structure: Atoms,
    parameters: NVTInputT,
    pp_path: str,
    orb_path: str,
):
    """Prepare VASP input files for NVT molecular dynamics.

    This function prepares POSCAR, KPOINTS, POTCAR, and INCAR files
    for a VASP NVT molecular dynamics calculation in the current directory.

    Parameters
    ----------
    structure : Atoms
        Atomic structure.
    parameters : NVTInputT
        NVT parameters including kspacing, encut, temperature range, etc.
    pp_path : str
        Path to VASP pseudopotential directory.
    orb_path : str
        Path to orbital files (not used for VASP).
    """
    incar = Incar.from_dict(params_default['nvt']['vasp'])
    # Handle predefined parameters in InputT
    # 检查这些参数！！！！！
    if parameters.md_thermostat == 'nhc':
        incar['MDALGO'] = 2
        incar['ISIF'] = 2
        incar['SMASS'] = 0
    elif parameters.md_thermostat == 'rescale_v':
        incar['MDALGO'] = 0
        incar['ISIF'] = 2
        incar['SMASS'] = -1
        incar['NBLOCK'] = 4
    
    prepare_vasp_inputs(
        structure=structure,
        pp_path=pp_path,
        kspacing=parameters.kspacing,
        incar=incar,
        incar_params=parameters.parameters,
    )


def _process_nvt_output_vasp(
    target_temp: float,
    plot: bool,
    output: Output,
    attempt: int = 1,
    check_nsw: Optional[int] = None,
    max_unconverged_ratio: float = 0.1,
) -> Tuple[bool, bool, float, float]:
    """Process VASP NVT output files and check convergence.

    This function extracts MD data from OSZICAR, checks SCF convergence
    and temperature convergence, and optionally generates plots.

    Parameters
    ----------
    target_temp : float
        Target temperature for NVT simulation.
    plot : bool
        Whether to generate plots.
    output : Output
        Output object to store results.
    attempt : int
        Current attempt number (for labeling).
    check_nsw : int, optional
        Number of steps to check for convergence. If None, check last 5% of steps.
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
    # Extract MD data from OSZICAR
    md_data = extract_md_data_from_oszicar()

    if md_data is None or len(md_data['steps']) == 0:
        output.stdout.append("ERROR: No MD data found in OSZICAR")
        return False, False, 0.0, float('inf')

    n_steps = len(md_data['steps'])
    output.stdout.append(f"MD steps completed: {n_steps}")

    # Default: check last 5% of steps for SCF convergence
    if check_nsw is None:
        check_nsw = max(50, n_steps // 20)
    max_unconverged = int(n_steps * max_unconverged_ratio)

    # Check SCF convergence
    scf_converged = check_md_convergence(
        n_steps=check_nsw,
        max_unconverged=max_unconverged,
    )

    if scf_converged:
        output.stdout.append(f"SCF convergence: PASSED")
    else:
        output.stdout.append(f"SCF convergence: FAILED (too many unconverged steps)")

    # Save MD data to file
    if attempt == 1:
        md_filename = 'md_vasp.dat'
    else:
        md_filename = f'md_vasp_attempt_{attempt}.dat'
    md_data_path = save_md_data(md_data, filename=md_filename)
    output.files.append(md_data_path)

    # Calculate temperature statistics
    temps = np.array(md_data['temperatures'])
    n_last = min(len(temps), 1000)
    last_temps = temps[-n_last:]

    avg_temp = np.mean(last_temps)
    temp_deviation = np.abs(last_temps - target_temp)
    max_deviation = np.max(temp_deviation)

    output.stdout.append(f"Average temperature (last {n_last} steps): {avg_temp:.1f} K")
    output.stdout.append(f"Max temperature deviation: {max_deviation:.1f} K")

    # Check temperature convergence (within 10% of target)
    temp_converged = max_deviation <= target_temp * 0.10
    if temp_converged:
        output.stdout.append(f"Temperature convergence: PASSED")
    else:
        output.stdout.append(
            f"Temperature convergence: FAILED "
            f"(deviation {max_deviation:.1f} K > threshold {target_temp * 0.10:.1f} K)"
        )

    # Generate plots if requested
    if plot:
        if attempt == 1:
            plot_filename = 'nvt_results.png'
        else:
            plot_filename = f'nvt_results_attempt_{attempt}.png'
        plot_path = plot_nvt_results(md_data, target_temp, filename=plot_filename)
        output.images.append(plot_path)

    return scf_converged, temp_converged, avg_temp, max_deviation


def extract_md_data_from_oszicar(oszicar_path: str = 'OSZICAR') -> Optional[Dict]:
    """Extract MD data from VASP OSZICAR file.

    Parameters
    ----------
    oszicar_path : str
        Path to OSZICAR file (default: 'OSZICAR').

    Returns
    -------
    dict or None
        Dictionary containing MD data:
        - 'steps': list of step numbers
        - 'temperatures': list of temperatures (K)
        - 'total_energies': list of total energies (eV)
        - 'potential_energies': list of potential energies (eV)
        - 'kinetic_energies': list of kinetic energies (eV)
        - 'potim': time step (fs)
    """
    if not os.path.isfile(oszicar_path):
        return None

    # Get POTIM from INCAR
    potim = 1.0
    if os.path.isfile('INCAR'):
        with open('INCAR', 'r') as f:
            for line in f:
                if 'POTIM' in line.upper():
                    parts = line.split()
                    if len(parts) >= 3:
                        try:
                            potim = float(parts[2])
                        except ValueError:
                            pass
                    break

    steps = []
    temperatures = []
    total_energies = []
    potential_energies = []
    kinetic_energies = []

    with open(oszicar_path, 'r') as f:
        for line in f:
            if 'T=' in line:
                values = line.split()
                try:
                    step = int(values[0])
                    T = float(values[2])
                    E_pot = float(values[8])
                    E_kin = float(values[10])
                    E_total = E_pot + E_kin

                    steps.append(step)
                    temperatures.append(T)
                    total_energies.append(E_total)
                    potential_energies.append(E_pot)
                    kinetic_energies.append(E_kin)
                except (ValueError, IndexError):
                    continue

    if len(steps) == 0:
        return None

    return {
        'steps': steps,
        'temperatures': temperatures,
        'total_energies': total_energies,
        'potential_energies': potential_energies,
        'kinetic_energies': kinetic_energies,
        'potim': potim,
    }


def save_md_data(md_data: Dict, filename: str = 'md_vasp.dat') -> str:
    """Save MD data to a file.

    Parameters
    ----------
    md_data : dict
        MD data dictionary from extract_md_data_from_oszicar().
    filename : str
        Output filename (default: 'md_vasp.dat').

    Returns
    -------
    str
        Path to the saved file.
    """
    with open(filename, 'w') as f:
        f.write(f"# Time step: {md_data['potim']} fs\n")
        f.write("# Step  Temperature  Total_Energy  E_pot  E_kin\n")

        for i in range(len(md_data['steps'])):
            f.write(
                f"{md_data['steps'][i]:6d} "
                f"{md_data['temperatures'][i]:10.1f} "
                f"{md_data['total_energies'][i]:14.6f} "
                f"{md_data['potential_energies'][i]:14.6f} "
                f"{md_data['kinetic_energies'][i]:14.6f}\n"
            )

        # Summary line
        avg_temp = np.mean(md_data['temperatures'])
        f.write(
            f"# Total steps: {len(md_data['steps'])}, Average T: {avg_temp:.1f} K\n"
        )

    return os.path.abspath(filename)


def check_md_convergence(
    n_steps: int,
    max_unconverged: int,
    oszicar_path: str = 'OSZICAR',
) -> bool:
    """Check if MD simulation SCF converged properly.

    This function checks for self-consistency errors in the last n_steps
    of the simulation. A simulation is considered converged if:
    1. No self-consistency errors in the last n_steps, OR
    2. Total unconverged steps <= max_unconverged

    Parameters
    ----------
    n_steps : int
        Number of steps to check (from the end).
    max_unconverged : int
        Maximum number of unconverged steps allowed.
    oszicar_path : str
        Path to OSZICAR file.

    Returns
    -------
    bool
        True if converged, False otherwise.
    """
    if not os.path.isfile(oszicar_path):
        return False

    # Read OSZICAR to find MD steps and errors
    t_lines = []  # Lines containing temperature (MD steps)
    error_lines = []  # Lines containing SCF errors

    with open(oszicar_path, 'r') as f:
        for i, line in enumerate(f):
            if 'T=' in line:
                t_lines.append(i)
            elif 'self-consistency was not achieved' in line.lower():
                error_lines.append(i)

    if len(t_lines) == 0:
        return False

    # No errors at all
    if len(error_lines) == 0:
        return True

    # Check if errors are within acceptable range
    # Get the last n_steps MD iterations
    start_idx = max(0, len(t_lines) - n_steps)
    check_range = t_lines[start_idx:]

    # Count errors in the check range
    errors_in_range = sum(1 for err_line in error_lines if err_line >= check_range[0])

    # Also check total errors
    total_errors = len(error_lines)

    # Converged if errors in check range are acceptable
    # AND total errors are within limit
    if errors_in_range == 0 and total_errors <= max_unconverged:
        return True

    return total_errors <= max_unconverged


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