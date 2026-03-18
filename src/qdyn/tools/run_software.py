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
        else:
            vasp_exe = 'vasp_std'

    # Launch VASP
    subprocess.run(['mpirun', '-np', str(nprocs), vasp_exe])
