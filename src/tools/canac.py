import logging
import multiprocessing
from pathlib import Path
import os
import numpy as np
import numpy.typing as npt
import natsort

from typing import Literal, Optional, List, Dict, Sequence

from .libcanac import aeolap
from .libcanac.utils import load_wfc, close_wfc, calc_tdolap

CA_NAC_VERSION = '1.2.0_beta'

def version():
    """Print and return the CA-NAC version banner."""
    logging.info(f"CA-NAC {CA_NAC_VERSION}\n"
                  "Should you have any question, please contact wbchu@fudan.edu.cn")

def extract_eigvals_and_nacs(
    run_dirs: List[str],
    software: Literal['vasp', 'cp2k', 'siesta', 'abacus', 'openmx', 'hamgnn'] = 'vasp',
    is_gamma_ver: bool = False,
    is_reorder: bool = False,
    is_alle: bool = False,
    bmin: int = 0,
    bmax: int = 0,
    ikpt: int = 1,
    ispin: int = 1,
    soc: bool = False,
    md_dt: float = 1.0,
    nproc: int = 1,
    bmin_stored: Optional[int] = None,
    bmax_stored: Optional[int] = None,
    dirs_sorted: bool = False,
):
    # input validation
    if not bmin_stored:
        bmin_stored = bmin
    if not bmax_stored:
        bmax_stored = bmax
    
    if not dirs_sorted:
        run_dirs = natsort.natsorted(run_dirs)

    assert is_alle is False

    if software == 'abacus':
        wfc_path = Path(run_dirs[0]) / 'WFC'
        nstep = len(os.listdir(wfc_path)) - 1
    else:
        nstep = len(run_dirs) - 1

    # main calculation
    multiprocessing.freeze_support()
    with multiprocessing.Pool(processes=nproc) as pool:
        indices = np.arange(nstep) + 1
        if software == 'abacus':
            run_dirs_A = [run_dirs[0]]
            run_dirs_B = [run_dirs[0]]
        else:
            run_dirs_A = run_dirs[:-1][::nproc]
            run_dirs_B = run_dirs[1:][::nproc]
        result = pool.apply_async(calc_tdolap_wrapper,
            kwds = {
                'indices': indices[::nproc],
                'run_dirs_A': run_dirs_A,
                'run_dirs_B': run_dirs_B,
                'software': software,
                'bmin': bmin_stored,
                'bmax': bmax_stored,
                'ikpt': ikpt,
                'ispin': ispin,
                'soc': soc,
            }
        )


def calc_tdolap_wrapper(
    indices: Sequence[int],
    run_dirs_A: Sequence[str],
    run_dirs_B: Sequence[str],
    software: str,
    bmin: int,
    bmax: int,
    ikpt: int,
    ispin: int,
    soc: bool = False,
    is_gamma_ver: bool = False,
    prev_output_path: str | None = None,
):
    nstep = len(indices)
    success = np.zeros(nstep, dtype=bool)
    tdolaps = []
    eigenvalues = []
    # read from prev_output if provided
    resume = False
    if prev_output_path:
        prev: Dict[str, npt.NDArray] = np.load(prev_output_path)
        resume = True

    if software == 'abacus':
        run_dir = run_dirs_A[0]
        for i, idx in enumerate(indices):
            if resume and f'tdolap_{idx}' in prev.keys():
                success[i] = True
                tdolaps.append(prev[f'tdolap_{idx}'])
                eigenvalues.append(prev[f'ev_{idx}'])
            f_waveA = Path(run_dir) / 'WFC' / f'wfk{ikpt}g{idx}_nao.txt'
            f_waveB = Path(run_dir) / 'WFC' / f'wfk{ikpt}g{idx+1}_nao.txt'
            if not f_waveA.exists() or not f_waveB.exists():
                success[i] = False
                continue
            wfc_A = load_wfc('abacus', f_waveA)
            wfc_B = load_wfc('abacus', f_waveB)
            S = None
            # TODO
    else:
        filename_mapping = {
            'vasp': 'WAVECAR',
            'siesta': 'Sys.fullBZ.WFSX',
            'hamgnn': 'wfc.npz'
        }
        for i, (idx, dirA, dirB) in enumerate(zip(indices, run_dirs_A, run_dirs_B)):
            if resume and f'tdolap_{idx}' in prev.keys():
                success[i] = True
                tdolaps.append(prev[f'tdolap_{idx}'])
                eigenvalues.append(prev[f'ev_{idx}'])
            f_waveA = Path(dirA) / filename_mapping[software]
            f_waveB = Path(dirB) / filename_mapping[software]
            f_S = None
            if not f_waveA.exists() or not f_waveB.exists():
                success[i] = False
                continue
            wfc_A = load_wfc(software, f_waveA)
            wfc_B = load_wfc(software, f_waveB)

            band_indices = np.arange(bmin, bmax+1)
            normalize = True if software == 'vasp' else False
            cic_t = np.stack(
                [wfc_A.readBandCoeff(ispin, ikpt, band_idx, norm=normalize)
                for band_idx in range(bmin, bmax+1)],
                axis=0
            )
            cic_tdt = np.stack(
                [wfc_B.readBandCoeff(ispin, ikpt, band_idx, norm=normalize)
                for band_idx in range(bmin, bmax+1)],
                axis=0
            )
            
            tdolap = calc_tdolap(software, cic_t, cic_tdt, S)

            # eigenvalues
            evs = wfc_A._bands[ispin-1, ikpt-1, bmin-1:bmax]
            # store
            eigenvalues.append(evs)
            # close
            close_wfc(software, wfc_A)

    return success

        



