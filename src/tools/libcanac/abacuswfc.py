from pathlib import Path
import numpy as np
import os

# only support nspin=1 for now.

ry2ev = 13.605693122994

class abacuswfc(object):
    '''
    Parser for an ABACUS NAO wavefunction file (e.g. WFC_NAO_K1.txt).

    Only supports single-spin (nspin=1), single-kpoint calculations.

    Properties
    ----------
    _fname  : str
        Path to the wavefunction file.
    _lgam   : bool
        True if this is a Gamma-point calculation (real-valued coefficients).
    _nspin  : int
        Number of spin channels. Always 1.
    _nkpts  : int
        Number of k-points. Always 1.
    _nbands : int
        Number of KS bands.
    _norbs  : int
        Number of NAO basis orbitals.
    _bands  : ndarray[float64], shape (nspin, nkpts, nbands)
        KS eigenvalues in eV.
    _occs   : ndarray[float64], shape (nspin, nkpts, nbands)
        KS occupation numbers.
    _wfc    : ndarray[float32] or ndarray[complex64], shape (nbands, norbs)
        NAO expansion coefficients. Stored as float32 for Gamma-point
        calculations, complex64 otherwise.
    '''

    def __init__(self, fnm: str, lgamma=False) -> None:
        self._fname = fnm
        self._lgam = lgamma
        self._nspin = 1
        self._nkpts = 1

        if not Path(fnm).exists():
            raise FileNotFoundError(f"Wavefunction file {fnm} not found.")

        self.readWF()

    def isGammaWfc(self):
        return True if self._lgam else False

    def readWF(self):
        _wfnm = open(self._fname)
        _wfnm.readline()  # k index
        kvec = list(map(float, _wfnm.readline().split()))
        nbnd = int(_wfnm.readline().split()[0])
        norb = int(_wfnm.readline().split()[0])
        if not hasattr(self, "_nbands"):
            self._nbands = nbnd
            self._norbs = norb
            self._bands = np.zeros((self._nspin, self._nkpts, nbnd), dtype=np.float64)  # energy nspin, nkpts, nbands
            self._occs = np.zeros((self._nspin, self._nkpts, nbnd), dtype=np.float64)  # occ nspin, nkpts, nbands
            if self.isGammaWfc():
                self._wfc = np.zeros((nbnd, norb), dtype=np.float32)  # shape: nspin, nkpts, nbands, norbitals
            else:
                self._wfc = np.zeros((nbnd, norb), dtype=np.complex64)  # shape: nspin, nkpts, nbands, norbitals

        # Loop over bands
        for ib in range(nbnd):
            _wfnm.readline()  # band index
            self._bands[0, 0, ib] = float(_wfnm.readline().split()[0])
            self._occs[0, 0, ib] = float(_wfnm.readline().split()[0])
            # Loop over orbitals
            tmp = []
            
            if self.isGammaWfc():
                for io in range(0, norb, 10):
                    tmp.extend(_wfnm.readline().split())
                tmp = np.asarray(tmp, dtype=np.float32)
                self._wfc[ib] = tmp
            else:
                for io in range(0, norb * 2, 10):
                    tmp.extend(_wfnm.readline().split())
                tmp = np.asarray(tmp, dtype=np.float32)
                self._wfc[ib] = tmp[0::2] + 1j * tmp[1::2]

        _wfnm.close()
        self._bands *= ry2ev

    def readBandCoeffs(self, iband: slice):
        '''
        Return the NAO expansion coefficients for the specified KS states.

        Parameters
        ----------
        iband : slice
            Band index slice into the first axis of _wfc.

        Returns
        -------
        ndarray, shape (n_selected_bands, norbs)
        '''
        return self._wfc[iband]

    def checkIndex(self, ispin, ikpt, iband):
        '''
        Assert that (ispin, ikpt, iband) are all 1-based valid indices.
        '''
        assert 1 <= ispin <= self._nspin,  'Invalid spin index!'
        assert 1 <= ikpt <= self._nkpts,  'Invalid kpoint index!'
        assert 1 <= iband <= self._nbands, 'Invalid band index!'
