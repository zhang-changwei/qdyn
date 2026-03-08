import subprocess
from ase import Atoms
from jobflow import job

from typing import Dict
from ..input import NVTInputT

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
) -> Dict:
    if software == 'VASP':
        _prepare_nvt_input_vasp()
        subprocess.run(['mpirun', '-np', '4', 'vasp'])
    else:
        raise NotImplementedError(f"NVT with software {software} is not implemented yet.")


def _prepare_nvt_input_vasp():
    pass
