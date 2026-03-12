from pathlib import Path
import numpy as np
import numpy.typing as npt
from typing import Any, Sequence

from . import mod_hungarian as hungarian

def orthogon(cic: npt.NDArray) -> npt.NDArray:
    r"""
    Orthogonalize the given complex matrix using the Löwdin method.

    .. math::
        S = C C^\dagger
        S = U \Lambda U^\dagger
        S^{-1/2} = U \Lambda^{-1/2} U^\dagger
        C_{\text{orth}} = S^{-1/2} C
    """

    S = cic @ cic.conj().T # S is hermite. shape (nbasis, nbasis)
    eigvals, eigvecs = np.linalg.eigh(S)
    inv_sqrt_eigvals = np.diag(1.0 / np.sqrt(eigvals))
    
    # Construct the orthogonalization matrix
    S_inv_sqrt = eigvecs @ inv_sqrt_eigvals @ eigvecs.conj().T
    
    # Orthogonalize the original matrix
    orthogonal_cic = S_inv_sqrt @ cic
    
    return orthogonal_cic


def reorder(tdolap: npt.NDArray):
    reorder_cost = np.real(tdolap.conj() * tdolap)
    res = hungarian.maximize(reorder_cost)
    perm1 = np.array(res, dtype=int)[:, 0] # [1,2,3,4]
    perm2 = np.array(res, dtype=int)[:, 1] # [1,3,2,4]

    return perm1, perm2


def reorder_apply(arr: npt.NDArray, perm: npt.NDArray) -> npt.NDArray:
    dim = len(arr.shape)
    if dim == 2:
        perm0 = np.arange(arr.shape[0], dtype=int)
        arr[np.ix_(perm0, perm)] = arr
        arr[np.ix_(perm, perm0)] = arr
    else: # dim == 1
        arr[perm] = arr

    return arr


def phase_correction(tdolap: npt.NDArray, is_gamma_ver: bool = True):
    if is_gamma_ver:
        cc2 = np.sign(np.diag(tdolap))
    else:
        tdolap_diag = np.diag(tdolap)
        cc2 = tdolap_diag / np.abs(tdolap_diag)
    cc1 = np.ones_like(cc2)
    
    return cc1, cc2


def phase_apply(tdolap: npt.NDArray, cc1: npt.NDArray, cc2: npt.NDArray, is_gamma_ver: bool = True):
    tdolap = cc1[:, None] * tdolap * cc2.conj()[None, :]
    nac = tdolap - tdolap.conj().T

    if is_gamma_ver:
        return nac.real # type: ignore
    return np.abs(nac) * np.sign(nac.real) # type: ignore


def load_wfc(software: str, source: str):
    if software == 'vasp':
        from vaspwfc import vaspwfc
        return vaspwfc(source)
    if software == 'siesta':
        from .siestawfc import siestawfc
        return siestawfc(source)
    if software == 'hamgnn':
        from .hamnetwfc import hamnetwfc
        return hamnetwfc(source)
    if software == 'abacus':
        from .abacuswfc import abacuswfc
        return abacuswfc(source)
    
    raise NotImplementedError(
        f"Software {software} is not supported for loading wavefunction coefficients."
    )


def close_wfc(software: str, wfc: Any):
    if software in ['vasp', 'siesta']:
        wfc._wfc.close()


def calc_tdolap(
    software: str,
    cic_A: npt.NDArray,
    cic_B: npt.NDArray,
    S: npt.NDArray | None = None,
) -> npt.NDArray:
    r"""
    Calculate the time-derivative overlap matrix (TDOLAP) between two sets of complex wavefunction coefficients.

    TDOLAP is defined as:
    
    .. math::
        \text{TDOLAP} = \langle \psi_A | \psi_B \rangle
    """

    # Ensure the input matrices are orthogonalized
    if software == 'vasp':
        cic_A = orthogon(cic_A)
        cic_B = orthogon(cic_B)

    # Calculate the TDOLAP
    if S is None:
        tdolap = cic_A.conj() @ cic_B.T
    else:
        tdolap = cic_A.conj() @ S @ cic_B.T
    
    return tdolap
