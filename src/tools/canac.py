import logging
import multiprocessing
import numpy

from typing import Literal, Optional, List

def extract_eigvals_and_nacs(
    run_dirs: List[str],
    software: Literal['VASP', 'CP2K', 'SIESTA', 'ABACUS', 'OPENMX', 'HAMGNN'] = 'VASP',
    is_gamma_ver: bool = False,
    is_reorder: bool = False,
    is_alle: bool = False,
    bmin: int = 0,
    bmax: int = 0,
    ikpt: int = 1,
    ispin: int = 1,
    md_dt: float = 1.0,
    nproc: Optional[int] = 1,
):
    pass

