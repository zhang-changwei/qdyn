import os
import subprocess
from pathlib import Path
from typing import Optional


def run_software(software: str, nprocs: int, is_alle: Optional[bool] = False) -> None:
    """Run the specified software with appropriate settings.

    Args:
        software: Name of the software to run (e.g., 'vasp').
        nprocs: Number of MPI processes to use.
        is_alle: Whether to use all-electron version (if applicable).
    """

    match software:
        case 'vasp':
            run_vasp(nprocs=nprocs, is_alle=is_alle)
        case _:
            raise NotImplementedError(f"Software '{software}' is not supported yet.")


def run_vasp(nprocs: int, is_alle: Optional[bool] = False) -> None:
    """Run VASP calculation using mpirun.

    Args:
        nprocs: Number of MPI processes
        is_alle: Whether to use all-electron VASP (vasp_ae)
    """
    # Check if using all-electron VASP
    if is_alle:
        vasp_exe = 'vasp_ae'
    else:
        # Read KPOINTS file to determine K-point count
        kpoints_file = Path('KPOINTS')
        if not kpoints_file.exists():
            raise FileNotFoundError("KPOINTS file not found")

        # Read K-point numbers in three directions from line 4
        lines = kpoints_file.read_text().strip().split('\n')
        kx, ky, kz = map(int, lines[3].split())

        # Use vasp_gam for single K-point, otherwise vasp_std
        if kx == 1 and ky == 1 and kz == 1:
            vasp_exe = 'vasp_gam'
            with open('INCAR', 'r') as f:
                lines = f.readlines()
            with open('INCAR', 'w') as incar:
                for line in lines:
                    if line.strip().startswith('KPAR'):
                        incar.write('KPAR = 1\n')
                    else:
                        incar.write(line)
        else:
            vasp_exe = 'vasp_std'
            with open('INCAR', 'r') as f:
                lines = f.readlines()
            with open('INCAR', 'w') as incar:
                for line in lines:
                    if line.strip().startswith('KPAR'):
                        incar.write('KPAR = 2\n')
                    else:
                        incar.write(line)

    # Launch VASP
    result = subprocess.run(['mpirun', '-np', str(nprocs), vasp_exe])
    if result.returncode != 0:
        # Read queue.err for real error details
        err_hint = ""
        if os.path.isfile("queue.err"):
            with open("queue.err") as f:
                lines = [l.strip() for l in f.readlines() if l.strip()]
                err_hint = "; ".join(lines[-5:]) if lines else ""
        raise RuntimeError(
            f"VASP exited with code {result.returncode}. "
            f"Last queue.err lines: {err_hint or '(empty)'}"
        )
