import logging
import multiprocessing
from pathlib import Path
import os
import numpy as np
import numpy.typing as npt
import natsort

from typing import Literal, Optional, List, Dict, Sequence

from .libcanac import aeolap
from .libcanac.utils import (load_wfc, close_wfc, 
                             reorder, reorder_apply, 
                             phase_correction, phase_apply,
                             calc_tdolap)

CA_NAC_VERSION = '1.2.0_beta'

def version():
    """Print and return the CA-NAC version banner."""
    logging.info(f"CA-NAC {CA_NAC_VERSION}\n"
                  "Should you have any question, please contact wbchu@fudan.edu.cn")

def extract_eigvals_and_nacs(
    run_dirs: List[str],
    software: Literal['vasp', 'cp2k', 'siesta', 'abacus', 'openmx', 'hamgnn'] = 'vasp',
    sysname: str = 'qdyn',
    is_gamma_ver: bool = False,
    is_reorder: bool = False,
    is_alle: bool = False,
    bmin: int = 0,
    bmax: int = 0,
    ikpt: int = 1,
    ispin: int = 1,
    soc: bool = False,
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
    nbasis = bmax_stored - bmin_stored + 1
    
    if not dirs_sorted:
        run_dirs = natsort.natsorted(run_dirs)

    assert is_alle is False

    if software == 'abacus':
        wfc_path = Path(run_dirs[0]) / 'WFC'
        nstep = len(os.listdir(wfc_path)) - 1
        run_dirs = [run_dirs[0]] * (nstep + 1) # all the same dir
    else:
        nstep = len(run_dirs) - 1
    indices = np.arange(nstep) # from 0

    olapT = np.complex128 if software == 'vasp' and not is_gamma_ver else np.float64

    # resume
    store_path = 'canac_nstep={}_bmin={}_bmax={}_ikpt={}_ispin={}_ae={}.npz'.format(
        nstep, bmin_stored, bmax_stored, ikpt, ispin, int(is_alle)
    )
    if Path(store_path).exists():
        logging.info(f"Found existing results at {store_path}. Loading...")
        data = np.load(store_path)
        check_list = data['success']
        tdolaps = data['tdolaps']
        eigenvalues = data['eigenvalues']
    else:
        check_list = np.zeros(nstep, dtype=np.bool)
        tdolaps = np.zeros((nstep, nbasis, nbasis), dtype=olapT)
        eigenvalues = np.zeros((nstep, nbasis), dtype=np.float64)

    # main calculation
    multiprocessing.freeze_support()
    with multiprocessing.Pool(processes=nproc) as pool:
        results = []
        paw_info = None

        # tdolap
        for idx in indices:
            # skip if already processed
            if check_list[idx]:
                continue

            result = pool.apply_async(calc_tdolap_wrapper,
                kwds = {
                    'index': idx,
                    'dirA': run_dirs[idx],
                    'dirB': run_dirs[idx + 1],
                    'software': software,
                    'bmin': bmin_stored,
                    'bmax': bmax_stored,
                    'ikpt': ikpt,
                    'ispin': ispin,
                    'soc': soc,
                    'is_alle': is_alle,
                    'sysname': sysname,
                }
            )
            results.append(result)

        for result in results:
            success, idx, tdolap, ev = result.get()
            if success:
                tdolaps[idx] = tdolap
                eigenvalues[idx] = ev
                check_list[idx] = True
        
    # save results
    np.savez(
        store_path,
        success=check_list,
        tdolaps=tdolaps,
        eigenvalues=eigenvalues
    )

    if np.all(check_list):
        logging.info("All steps processed successfully.")
        with multiprocessing.Pool(processes=nproc) as pool:
            results = []
            # nac
            for idx in indices:
                result = pool.apply_async(calc_nac_wrapper,
                    kwds = {
                        'tdolap': tdolaps[idx],
                        'is_gamma_ver': is_gamma_ver,
                        'is_reorder': is_reorder,
                    }
                )
                results.append(result)

            cc_left = np.ones(nbasis, dtype=olapT)
            perm_left = np.arange(nbasis, dtype=int)
            nacs = np.zeros((nstep, nbasis, nbasis), dtype=np.float64)

            for idx, result in enumerate(results):
                tdolap, _, cc2, _, perm2 = result.get()
                if is_reorder:
                    perm_right = perm_left[perm2]
                    # The diff between perm_left and perm_right is handled before
                    # So add perm_left only to cc2, tdolap
                    cc2 = reorder_apply(cc2, perm_left)
                    eigenvalues[idx] = reorder_apply(eigenvalues[idx], perm_left)
                    tdolap = reorder_apply(tdolap, perm_left)

                cc_right = cc_left * cc2
                
                nac = phase_apply(tdolap, cc_left, cc_right, is_gamma_ver)

                # save
                nacs[idx] = nac

                # update
                cc_left = cc_right
                if is_reorder:
                    perm_left = perm_right # type: ignore

        # save in HFNAMD format
        logging.info("Saving results in HFNAMD format...")
        np.savetxt('EIGTXT', eigenvalues)
        np.savetxt('NATXT', nacs)



def calc_tdolap_wrapper(
    index: int, # from 0 to nstep-1
    dirA: str,
    dirB: str,
    software: str,
    bmin: int,
    bmax: int,
    ikpt: int,
    ispin: int,
    soc: bool = False,
    is_alle: bool = False,
    sysname: str = 'qdyn',
):

    waveA_mapping = {
        'vasp': 'WAVECAR',
        'abacus': f'OUT.{sysname}/WFC/wfk{ikpt}g{index+1}_nao.txt',
        'siesta': f'{sysname}.fullBZ.WFSX',
        'hamgnn': 'wfc.npz'
    }
    waveB_mapping = {
        'vasp': 'WAVECAR',
        'abacus': f'OUT.{sysname}/WFC/wfk{ikpt}g{index+2}_nao.txt',
        'siesta': f'{sysname}.fullBZ.WFSX',
        'hamgnn': 'wfc.npz'
    }

    f_waveA = Path(dirA) / waveA_mapping[software]
    f_waveB = Path(dirB) / waveB_mapping[software]
    f_S = None

    if not f_waveA.exists() or not f_waveB.exists():
        success = False
        return success, index, None, None
    wfc_A = load_wfc(software, str(f_waveA))
    wfc_B = load_wfc(software, str(f_waveB))
    S = None

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
    ev = wfc_A._bands[ispin-1, ikpt-1, bmin-1:bmax]

    # close
    close_wfc(software, wfc_A)
    close_wfc(software, wfc_B)

    return True, index, tdolap, ev

def calc_nac_wrapper(
    tdolap: npt.NDArray,
    is_gamma_ver: bool = False,
    is_reorder: bool = False,
    is_phase: bool = True,
):
    # reorder
    perm1, perm2 = None, None
    if is_reorder:
        perm1, perm2 = reorder(tdolap)
        tdolap[np.ix_(perm1, perm2)] = tdolap

    # phase correction
    cc1, cc2 = None, None
    if is_phase:
        cc1, cc2 = phase_correction(tdolap, is_gamma_ver)

    return tdolap, cc1, cc2, perm1, perm2

def plot_tdeigenvalues():
    pass

