from pathlib import Path
from typing import List, Dict, Any

import numpy as np
import numpy.typing as npt
from jobflow import job

from ..input import PreNAMDInputT
from .canac import extract_eigvals_and_nacs
from .dephase import calculate_dephasing_time

@job
def run_pre_namd(
    software: str,
    parameters: PreNAMDInputT,
    run_dirs: List[str],
    prev_output: Dict[str, Any],
    nproc: int = 1,
    plot: bool = False,
    prepare_input_only: bool = False,
):
    # No input files required
    if prepare_input_only:
        return

    # basics
    is_gamma_ver = False
    if software == 'vasp':
        with open(f'{run_dirs[0]}/OUTCAR', 'r') as f:
            head = f.readline()
            if head.strip().endswith('gamma-only'):
                is_gamma_ver = True

    if isinstance(parameters.bmin, str):
        bmin_ = parameters.bmin.lower()
        bmin_.replace('vbm', prev_output['vbm'])
        bmin_.replace('cbm', prev_output['cbm'])
        bmin_ = eval(bmin_)
    else:
        bmin_ = parameters.bmin
    if isinstance(parameters.bmax, str):
        bmax_ = parameters.bmax.lower()
        bmax_.replace('vbm', prev_output['vbm'])
        bmax_.replace('cbm', prev_output['cbm'])
        bmax_ = eval(bmax_)
    else:
        bmax_ = parameters.bmax

    extract_eigvals_and_nacs(
        run_dirs=run_dirs,
        software=software,
        is_gamma_ver=is_gamma_ver,
        is_reorder=parameters.adv.reorder,
        is_alle=parameters.adv.alle,
        bmin=bmin_,
        bmax=bmax_,
        ikpt=parameters.adv.ikpt,
        ispin=parameters.adv.ispin,
        md_dt=parameters.md_dt,
        nproc=nproc,
    )

    images = []
    if plot:
        pass

    # DEPHTIME
    if parameters.surface_hopping == 'DISH':
        output = calculate_dephasing_time(
            working_dir=Path.cwd(),
            energies_path='EIGTXT',
            md_dt=parameters.md_dt,
            plot=plot,
        )
        images.extend(output['images'])

    return {
        'run_dir': str(Path.cwd()),
        'software': software,
        'images': images,
        'EIGTXT': str(Path.cwd() / 'EIGTXT'),
        'NATXT':  str(Path.cwd() / 'NATXT'),
        'DEPHTIME': (str(Path.cwd() / 'DEPHTIME') 
                     if parameters.surface_hopping == 'DISH' 
                     else None),
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
