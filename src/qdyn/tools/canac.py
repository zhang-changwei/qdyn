import logging
from collections.abc import Generator
from pathlib import Path
import os
import re
import numpy as np
import numpy.typing as npt

from typing import Literal, Any, Sequence, cast

from ..input import ScissorInputT
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

def extract_tdolaps(
    run_dirs: list[str],
    software: Literal['vasp', 'cp2k', 'siesta', 'abacus', 'openmx', 'hamgnn'] = 'vasp',
    sysname: str = 'qdyn',
    is_gamma_ver: bool = False,
    is_alle: bool = False,
    bmin: int = 0,
    bmax: int = 0,
    ikpt: int = 1,
    ispin: int = 1,
    soc: bool = False,
    nproc: int = 1,
    batch_size: int = 0,
    dirs_sorted: bool = False,
    generator: bool = False,
) -> Generator[dict[str, Any] | None, None, None]:
    import multiprocessing
    # input validation
    nbasis = bmax - bmin + 1
    if not batch_size:
        batch_size = nproc
    
    if not dirs_sorted:
        import natsort
        run_dirs = natsort.natsorted(run_dirs)

    if is_alle and is_gamma_ver:
        raise ValueError("Alle and gamma version cannot be both True.")
    if software != 'vasp' and is_alle:
        raise ValueError("Alle is only supported for VASP.")
    if software in ['abacus', 'siesta', 'openmx', 'hamgnn']:
        if not is_gamma_ver:
            raise ValueError(f"{software} only supports gamma version currently.") # S(gamma) only

    if software == 'abacus':
        wfc_path = Path(run_dirs[0]) / 'WFC'
        nstep = len(list(wfc_path.glob('wfck1g*'))) - 1
        run_dirs = [run_dirs[0]] * (nstep + 1) # all the same dir
    else:
        nstep = len(run_dirs) - 1
    indices = np.arange(nstep) # from 0

    olapT = np.complex128 if software == 'vasp' and not is_gamma_ver else np.float64

    # resume
    store_path = 'tdolap_nstep={}_bmin={}_bmax={}_ikpt={}_ispin={}_gam={}_ae={}.npz'.format(
        nstep, bmin, bmax, ikpt, ispin, int(is_gamma_ver), int(is_alle)
    )
    if Path(store_path).is_file():
        logging.info(f"Found existing results at {store_path}. Loading...")
        data = np.load(store_path)
        check_list = data['success']
        tdolaps = data['tdolaps']
        eigenvalues = data['eigenvalues']
    else:
        check_list = np.zeros(nstep, dtype=bool)
        tdolaps = np.zeros((nstep, nbasis, nbasis), dtype=olapT)
        eigenvalues = np.zeros((nstep, nbasis), dtype=np.float64)

    # main calculation
    multiprocessing.freeze_support()
    with multiprocessing.Pool(processes=nproc) as pool:
        results = []
        paw_info = None
        # for alle, do some checkings beforehand
        if is_alle:
            dir_first = check_first_dir_alle(run_dirs)
            aeolap.test(bmin, bmax, dir_first)
            paw_info = aeolap.PawProj_info(dir_first)

        # tdolap
        if generator:
            for idx_start in indices[::batch_size]:
                for idx in indices[idx_start : idx_start + batch_size]:
                    # skip if already processed
                    if check_list[idx]:
                        continue

                    result = pool.apply_async(calc_tdolap_wrapper,
                        kwds = {
                            'index': idx,
                            'dirA': run_dirs[idx],
                            'dirB': run_dirs[idx + 1],
                            'software': software,
                            'bmin': bmin,
                            'bmax': bmax,
                            'ikpt': ikpt,
                            'ispin': ispin,
                            'soc': soc,
                            'is_alle': is_alle,
                            'paw_info': paw_info,
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
                
                # reset results
                results = []

                yield
        else:
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
                        'bmin': bmin,
                        'bmax': bmax,
                        'ikpt': ikpt,
                        'ispin': ispin,
                        'soc': soc,
                        'is_alle': is_alle,
                        'paw_info': paw_info,
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
        allow_pickle=False,
        success=check_list,
        tdolaps=tdolaps,
        eigenvalues=eigenvalues,
    )

    yield {
        "tdolap_path": str(Path.cwd() / store_path),
        "tdolaps": tdolaps,
        "eigenvalues": eigenvalues,
    }


def collect_tdolap_output(
    *args: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    out: dict[str, Any] | None = None
    for item in extract_tdolaps(*args, **kwargs):
        if item is not None:
            out = item
    if out is None:
        raise RuntimeError("CA-NAC extraction did not produce a tdolap output.")
    return out


def extract_nacs(
    data: dict[str, npt.NDArray], 
    tdolap_path: str | Path,
    is_reorder: bool = False, 
    nproc: int = 1,
) -> dict[str, Any]:
    import multiprocessing

    pattern = re.compile(r"tdolap_nstep=(\d+)_bmin=(\d+)_bmax=(\d+)_ikpt=(\d+)_ispin=(\d+)_gam=(\d+)_ae=(\d+).npz")
    m = pattern.match(os.path.basename(tdolap_path))
    if m is None:
        raise ValueError(f"tdolap filename does not match expected pattern: {tdolap_path}")
    nstep = int(m.group(1))
    bmin = int(m.group(2))
    bmax = int(m.group(3))
    is_gamma_ver = bool(int(m.group(6)))

    check_list = data['success']
    tdolaps = data['tdolaps']
    eigenvalues = data['eigenvalues']

    nbasis = bmax - bmin + 1
    indices = np.arange(nstep) # from 0
    olapT = tdolaps.dtype

    store_path = 'nac_nstep={}_bmin={}_bmax={}_ikpt={}_ispin={}_gam={}_ae={}.npz'.format(
        nstep, bmin, bmax, m.group(4), m.group(5), m.group(6), m.group(7)
    )

    nacs = np.zeros((nstep, nbasis, nbasis), dtype=np.float64)
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
    
        np.savez(
            store_path,
            allow_pickle=False,
            nacs=nacs,
            eigenvalues=eigenvalues,
        )
    
    return {
        "nac_path": str(Path.cwd() / store_path),
        "nacs": nacs,
        "eigenvalues": eigenvalues,
    }


def save_hfnamd_inputs(
    nac_path: str | Path,
    bmin: int,
    bmax: int,
    out_dir: str | Path = '.',
    scissor: ScissorInputT | None = None,
):
    pattern = re.compile(r"nac_nstep=(\d+)_bmin=(\d+)_bmax=(\d+)_ikpt=(\d+)_ispin=(\d+)_gam=(\d+)_ae=(\d+).npz")
    m = pattern.match(os.path.basename(nac_path))
    if m is None:
        raise ValueError(f"NAC filename does not match expected pattern: {nac_path}")
    nstep = int(m.group(1))
    bmin_stored = int(m.group(2))
    bmax_stored = int(m.group(3))
    if bmin < bmin_stored or bmax > bmax_stored or bmax < bmin:
        raise ValueError("Requested band range exceeds the range stored in nac file.\n"
                         "Or bmax < bmin.")

    data = np.load(nac_path)
    nacs = data['nacs']
    eigenvalues = data['eigenvalues']

    # save in HFNAMD format
    logging.info("Saving results in HFNAMD format...")
    bot = bmin - bmin_stored
    top = bmax - bmin_stored + 1

    # scissor operation
    if scissor:
        bot_scissor = bot + scissor.scissor_bmin - 1
        if bot_scissor >= top:
            raise ValueError("Scissor bmin is out of the requested band range.")
        eigenvalues[:, bot_scissor:top] += scissor.scissor_shift
    
    np.savetxt(os.path.join(out_dir, 'EIGTXT'), 
               eigenvalues[:, bot:top])
    np.savetxt(os.path.join(out_dir, 'NATXT'), 
               nacs[:, bot:top, bot:top].reshape(nstep, -1))



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
    paw_info: aeolap.PawProj_info | None = None,
    sysname: str = 'qdyn',
):
    # file checking and loading
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

    if not f_waveA.is_file() or not f_waveB.is_file():
        success = False
        return success, index, None, None
    if is_alle:
        f_normalcarA = Path(dirA) / 'NormalCAR'
        f_normalcarB = Path(dirB) / 'NormalCAR'
        if not f_normalcarA.is_file() or not f_normalcarB.is_file():
            success = False
            return success, index, None, None
    wfc_A = load_wfc(software, str(f_waveA))
    wfc_B = load_wfc(software, str(f_waveB))

    S = None
    if software in ['hamgnn', 'siesta', 'abacus', 'openmx']:
        if (Path(dirA) / 'overlap.npz').is_file():
            from scipy.sparse import csr_array as csr
            f_SA = Path(dirA) / 'overlap.npz'
            S_raw = np.load(f_SA)
            S_data = S_raw['data']
            S_indices = S_raw['indices']
            S_indptr = S_raw['indptr']
            S_shape = S_raw['shape']
            S = csr((S_data, S_indices, S_indptr), shape=S_shape, dtype=np.float32)
            S = S.toarray()
        elif (Path(dirA) / 'overlap.npy').is_file():
            f_SA = Path(dirA) / 'overlap.npy'
            S = np.load(f_SA)
        else:
            success = False
            return success, index, None, None

    # validations
    if software == 'vasp':
        if wfc_A._nbands != wfc_B._nbands:
            raise ValueError("Number of bands mismatch between two steps.")
        if wfc_A._nplws[ikpt-1] != wfc_B._nplws[ikpt-1]: # type: ignore
            raise ValueError("Number of plane waves mismatch between two steps.")

    # read coefficients
    normalize = True if (software == 'vasp' and not is_alle) else False
    if software in ['vasp', 'siesta']:
        cic_t = np.stack(
            [wfc_A.readBandCoeff(ispin, ikpt, band_idx, norm=normalize) # type: ignore
            for band_idx in range(bmin, bmax+1)],
            axis=0
        )
        cic_tdt = np.stack(
            [wfc_B.readBandCoeff(ispin, ikpt, band_idx, norm=normalize) # type: ignore
            for band_idx in range(bmin, bmax+1)],
            axis=0
        )
    else: # hamgnn, abacus
        cic_t = wfc_A.readBandCoeffs(slice(bmin-1, bmax)) # type: ignore
        cic_tdt = wfc_B.readBandCoeffs(slice(bmin-1, bmax)) # type: ignore

    # calculate tdolap
    tdolap = calc_tdolap(software, cic_t, cic_tdt, S)

    if is_alle:
        from spinorb import read_cproj_NormalCar
        paw_info = cast(aeolap.PawProj_info, paw_info)

        cprojs1 = read_cproj_NormalCar(os.path.join(dirA, 'NormalCAR'))
        cprojs2 = read_cproj_NormalCar(os.path.join(dirB, 'NormalCAR'))

        # On the fly verify
        s_olap = cic_t.conj() @ cic_t.T
        s_aug_olap = aeolap.ae_aug_olap_martrix(
            bmin, bmax, cprojs1, cprojs1, paw_info,
            wfc_A._nkpts, wfc_A._nbands, ikpt, ispin
        )
        s_olap += s_aug_olap
        aeolap.realtime_checking(s_olap, dirA)

        # add the augmentation part to tdolap
        tdolap += aeolap.ae_aug_olap_martrix(
            bmin, bmax, cprojs1, cprojs2, paw_info,
            wfc_A._nkpts, wfc_A._nbands, ikpt, ispin
        )

    # eigenvalues
    ev = wfc_A._bands[ispin-1, ikpt-1, bmin-1:bmax] # type: ignore

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

def check_first_dir_alle(dirs: Sequence[str]):
    for dir in dirs:
        if (Path(dir) / 'WAVECAR').is_file() and (Path(dir) / 'NormalCAR').is_file():
            return dir
    else:
        raise FileNotFoundError("No directory contains both WAVECAR and NormalCAR for alle checking.")

def plot_tdeigenvalues():
    pass
