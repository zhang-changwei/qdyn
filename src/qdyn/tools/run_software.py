import os
import subprocess
from pathlib import Path
from typing import Callable

def run_software(software: str, nprocs: int, monitor: Callable | None = None, **kwargs) -> None:
    """Run the specified software with appropriate settings.

    Args:
        software: Name of the software to run (e.g., 'vasp').
        nprocs: Number of MPI processes to use.
        monitor: Optional callback function to monitor the calculation progress.
    """

    if software == 'vasp':
        run_vasp(nprocs, **kwargs)
    else:
        raise NotImplementedError(f"Software '{software}' is not supported yet.")


def run_vasp(nprocs: int, is_alle: bool | None = False, **kwargs) -> None:
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
        else:
            vasp_exe = 'vasp_std'

    # Launch VASP
    if "omp" in kwargs:
        result = subprocess.run([f'OMP_NUM_THREADS={kwargs["omp"]}', 
                                 'mpirun', '-np', str(nprocs), vasp_exe])
    else:
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
