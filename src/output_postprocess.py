import os
from typing import Dict, Optional

import matplotlib

matplotlib.use('agg')
import matplotlib.pyplot as plt
import numpy as np


# ===========================================================================
# Universal functions
# ===========================================================================
def check_scf_convergence(
    converged_list: list[bool],
    check_nsw: Optional[int] = None,
    max_unconverged_ratio: float = 0.01,
) -> bool:
    """Check SCF convergence from MD data (universal for all software).

    This function checks if SCF converged properly based on the converged
    flags in the MD data.

    Parameters
    ----------
    converged_list : list of bool
        List of SCF convergence flags for each MD step.
    check_nsw : int, optional
        Number of steps to check (from the end). If None, check last 5% of steps.
    max_unconverged_ratio : float
        Maximum ratio of unconverged steps allowed (default: 0.01 = 1%).

    Returns
    -------
    bool
        True if SCF converged properly, False if there are too many unconverged steps.
    """

    n_steps = len(converged_list)

    if n_steps == 0:
        raise ValueError("No convergence data available to check SCF convergence.")

    # Default: check last 5% of steps
    if check_nsw is None:
        check_nsw = n_steps // 10

    # Get the range to check
    check_range = converged_list[-check_nsw:]

    # n_total = len(check_range)
    n_unconverged = sum(1 for c in check_range if not c)
    max_unconverged = int(check_nsw * max_unconverged_ratio)

    # Converged if unconverged steps in check range <= max_unconverged
    converged = n_unconverged <= max_unconverged

    return converged


def save_md_data(md_data: Dict, md_dt: float, filename: str = 'md.dat') -> str:
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
        - 'md_dt': time step (fs)
    filename : str
        Output filename (default: 'md.dat').

    Returns
    -------
    str
        Path to the saved file.
    """
    with open(filename, 'w') as f:
        f.write(f"# Time step (fs): {md_dt}\n")
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


def plot_md_results(
    md_data: Dict,
    filename: str,
    target_temp: Optional[float] = None,
) -> str:
    """Plot MD simulation results.

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

    if target_temp is not None:
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


# ===========================================================================
# VASP specific functions
# ===========================================================================
def extract_md_data_from_oszicar(oszicar_path: str = 'OSZICAR') -> Dict:
    """Extract MD data and SCF convergence info from VASP OSZICAR file.

    Parameters
    ----------
    oszicar_path : str
        Path to OSZICAR file (default: 'OSZICAR').

    Returns
    -------
    dict or None
        Dictionary containing MD data (unified format for all software):
        - 'steps': list of step numbers
        - 'temperatures': list of temperatures (K)
        - 'total_energies': list of total energies (eV)
        - 'potential_energies': list of potential energies (eV)
        - 'kinetic_energies': list of kinetic energies (eV)
        - 'converged': list of bool, whether each SCF step converged
        - 'potim': time step (fs)
    """
    if not os.path.isfile(oszicar_path):
        raise FileNotFoundError(
            f"OSZICAR file not found at {oszicar_path}. Please check the output for errors."
        )

    nelm = 60  # default value in vasp
    if os.path.isfile('INCAR'):
        with open('INCAR', 'r') as f:
            for line in f:
                if 'NELM' in line.upper():
                    parts = line.split()
                    if len(parts) >= 3:
                        try:
                            nelm = float(parts[2])
                        except ValueError:
                            pass
                    break
    steps = []
    temperatures = []
    total_energies = []
    potential_energies = []
    kinetic_energies = []
    converged = []

    with open(oszicar_path, 'r') as f:
        lines = f.readlines()

    for i in range(len(lines)):
        line = lines[i]
        if 'T=' in line:
            values = line.split()
            try:
                step = int(values[0])
                T = float(values[2])
                E_pot = float(values[8])
                E_kin = float(values[10])
                E_total = E_pot + E_kin

                # Check if this step is unconverged (fake scf convergence check)
                step_converged = True
                last_line = lines[i - 1]
                if int(last_line.split()[1]) == nelm:
                    step_converged = False

                steps.append(step)
                temperatures.append(T)
                total_energies.append(E_total)
                potential_energies.append(E_pot)
                kinetic_energies.append(E_kin)
                converged.append(step_converged)
            except (ValueError, IndexError):
                pass

    if len(steps) == 0:
        raise ValueError("No valid MD steps found in OSZICAR file.")

    return {
        'steps': steps,
        'temperatures': temperatures,
        'total_energies': total_energies,
        'potential_energies': potential_energies,
        'kinetic_energies': kinetic_energies,
        'converged': converged,
    }
