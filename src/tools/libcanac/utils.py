from pathlib import Path
import numpy as np
import numpy.typing as npt

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

def load_wfc(software: str, source: str | Path):
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
    if sofware == 'vasp':
        wfc._wfc.close()

def calc_tdolap(
    software: str,
    cic_A: npt.NDArray,
    cic_B: npt.NDArray,
    S: npt.NDArray | None = None,
) -> npt.NDArray:
    """
    Calculate the time-derivative overlap matrix (TDOLAP) between two sets of complex wavefunction coefficients.

    TDOLAP is defined as:
    
    .. math::
        \text{TDOLAP} = C_A^\dagger C_B
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