from pathlib import Path
from typing import List

import numpy as np
import numpy.typing as npt
from jobflow import job

from ..input import PreNAMDInputT

@job
def run_pre_namd(
    software: str,
    parameters: PreNAMDInputT,
    run_dirs: List[str],
    nproc: int = 1,
    plot: bool = False,
    prepare_input_only: bool = False,
):
    pass

    # basics
    is_gamma_ver = False
    if software == 'vasp':
        with open(f'{run_dirs[0]}/OUTCAR', 'r') as f:
            head = f.readline()
            if head.strip().endswith('gamma-only'):
                is_gamma_ver = True

    
    
    # INICON
    inicon = sample_initial_conditions(2, 100, bmin, bmax, parameters.nsample)
    np.savetxt('INICON', inicon, fmt='%d')

    return {
        'run_dir': str(Path.cwd()),
        'software': software,
        'EIGTXT': str(Path.cwd() / 'EIGTXT'),
        'NATXT':  str(Path.cwd() / 'NATXT'),
        'INICON': str(Path.cwd() / 'INICON'),
    }


def sample_initial_conditions(
    time_start: int,
    time_stop: int,
    bmin: int,
    bmax: int,
    nsample: int = 200,
) -> npt.NDArray[np.int32]:
    rng = np.random.default_rng()
    inicon = np.zeros([nsample, 2], dtype=np.int32)
    inicon[:, 0] = rng.integers(time_start, time_stop, size=nsample, endpoint=True)
    inicon[:, 1] = rng.integers(bmin, bmax, size=nsample, endpoint=True)
    return inicon
