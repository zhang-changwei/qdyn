from pathlib import Path
import numpy as np
import numpy.typing as npt
from typing import Any, Sequence

from . import mod_hungarian as hungarian

def orthogonalize(cic: npt.NDArray, is_gamma_ver: bool = False) -> npt.NDArray:
    r"""
    Orthogonalize the given complex matrix using the Löwdin method.

    .. math::
        S = C C^\dagger
        S = U \Lambda U^\dagger
        S^{-1/2} = U \Lambda^{-1/2} U^\dagger
        C_{\text{orth}} = S^{-1/2} C

    Gamma-only VASP stores scaled half-sphere coefficients. Their physical
    Gram matrix is the real part of the complex coefficient Gram matrix.
    """

    S = cic @ cic.conj().T # S is hermite. shape (nbasis, nbasis)
    if is_gamma_ver:
        S = S.real
    eigvals, eigvecs = np.linalg.eigh(S)
    threshold = np.finfo(eigvals.dtype).eps * len(eigvals) * eigvals[-1]
    if np.any(eigvals <= threshold):
        raise ValueError("Cannot orthogonalize linearly dependent wavefunctions.")
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
    """Return unit-modulus relative phases, including at zero overlap.

    A zero diagonal overlap does not determine a phase. Gamma calculations
    use -1, matching CA-NAC; complex calculations retain the previous phase.
    """
    tdolap_diag = np.diag(tdolap)
    if is_gamma_ver:
        cc2 = np.ones_like(tdolap_diag.real)
        cc2[tdolap_diag.real <= 0] = -1
    else:
        magnitudes = np.abs(tdolap_diag)
        cc2 = np.ones_like(tdolap_diag)
        np.divide(tdolap_diag, magnitudes, out=cc2, where=magnitudes > 0)
    cc1 = np.ones_like(cc2)
    
    return cc1, cc2


def phase_apply(tdolap: npt.NDArray, cc1: npt.NDArray, cc2: npt.NDArray, is_gamma_ver: bool = True):
    tdolap = cc1[:, None] * tdolap * cc2.conj()[None, :]
    nac = tdolap - tdolap.conj().T

    if is_gamma_ver:
        return nac.real # type: ignore
    return np.abs(nac) * np.sign(nac.real) # type: ignore


def load_wfc(software: str, source: str, is_gamma_ver: bool = False):
    if software == 'vasp':
        from vaspwfc import vaspwfc
        # vasp always store wavefunction in complex, is_gamma_ver can be omitted.
        return vaspwfc(source, lgamma=is_gamma_ver)
    if software == 'siesta':
        from .siestawfc import siestawfc
        return siestawfc(source, lgamma=is_gamma_ver)
    if software == 'hamgnn':
        from .hamgnnwfc import hamngnnwfc
        return hamngnnwfc(source)
    if software == 'abacus':
        from .abacuswfc import abacuswfc
        return abacuswfc(source, lgamma=is_gamma_ver)
    
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
    *,
    orthogon: bool = False,
    is_gamma_ver: bool = False,
) -> npt.NDArray:
    r"""
    Calculate the time overlap matrix (TDOLAP) between wavefunctions.

    TDOLAP is defined as:
    
    .. math::
        \text{TDOLAP} = \langle \psi_A | \psi_B \rangle

    Coefficients are used unchanged by default, as required when adding PAW
    augmentation from the original projector coefficients. Optional Lowdin
    orthogonalization is supported only for pseudo VASP plane-wave overlaps.
    For Gamma-only VASP, the scaled half-sphere overlap is made real before
    it is returned; `is_gamma_ver` selects the corresponding real Gram
    matrix when orthogonalization is requested.
    """

    if orthogon:
        if software != 'vasp' or S is not None:
            raise ValueError("Orthogonalization requires VASP plane-wave coefficients without an overlap metric.")
        cic_A = orthogonalize(cic_A, is_gamma_ver=is_gamma_ver)
        cic_B = orthogonalize(cic_B, is_gamma_ver=is_gamma_ver)

    # Calculate the TDOLAP
    if S is None:
        tdolap = cic_A.conj() @ cic_B.T
    else:
        tdolap = cic_A.conj() @ S @ cic_B.T
    
    if is_gamma_ver:
        return tdolap.real
    return tdolap
