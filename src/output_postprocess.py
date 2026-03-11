import os
from typing import Dict, Optional


# ===========================================================================
# VASP specific functions
# ===========================================================================
def extract_md_data_from_oszicar(oszicar_path: str = 'OSZICAR') -> Optional[Dict]:
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
    converged = []

    with open(oszicar_path, 'r') as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i]
        if 'T=' in line:
            values = line.split()
            try:
                step = int(values[0])
                T = float(values[2])
                E_pot = float(values[8])
                E_kin = float(values[10])
                E_total = E_pot + E_kin

                # Check if next line contains SCF error (within same MD step)
                step_converged = True
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    if 'self-consistency was not achieved' in next_line.lower():
                        step_converged = False

                steps.append(step)
                temperatures.append(T)
                total_energies.append(E_total)
                potential_energies.append(E_pot)
                kinetic_energies.append(E_kin)
                converged.append(step_converged)
            except (ValueError, IndexError):
                pass
        i += 1

    if len(steps) == 0:
        return None

    return {
        'steps': steps,
        'temperatures': temperatures,
        'total_energies': total_energies,
        'potential_energies': potential_energies,
        'kinetic_energies': kinetic_energies,
        'converged': converged,
        'potim': potim,
    }
