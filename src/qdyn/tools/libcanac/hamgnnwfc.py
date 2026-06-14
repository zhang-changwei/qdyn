from pathlib import Path
import numpy as np


class hamngnnwfc(object):
    '''
    Wavefunction container for HamGNN exact-diagonalisation results.

    Reads eigenvalues and eigenvectors from a compressed NumPy archive (.npz).
    Only supports Gamma-point, single-spin calculations.

    Properties
    ----------
    _fname      : str
        Path to the .npz wavefunction file.
    _lgam       : bool
        Always True (Gamma-point only).
    _nspin      : int
        Number of spin channels. Always 1.
    _nkpts      : int
        Number of k-points. Always 1.
    _nbands     : int
        Number of KS bands stored. Equals _norbs in normal mode; may be
        smaller in huge mode (only a subset of eigenstates is kept).
    _norbs      : int
        Number of NAO basis orbitals (= Hamiltonian matrix dimension).
    _bands      : ndarray[float64], shape (nspin, nkpts, nbands)
        KS eigenvalues in the units provided by HamGNN.
    _wfc        : ndarray, shape (nbands, norbs)
        Eigenvector coefficients. Real-valued for Gamma calculations.
    _huge_mode  : bool
        True when nbands < norbs, i.e. only a subset of eigenstates is stored.
        Attribute is only set in this case; check with ``hasattr`` before use.
    '''

    def __init__(self, fnm: str = 'wfc.npz') -> None:
        '''
        Parameters
        ----------
        fnm : str
            Path to the .npz file containing ``eigenvalues`` (shape: norbs,)
            and ``wfc`` (shape: nbands, norbs). Only Gamma-point, single-spin
            calculations are supported. When all eigenstates are present,
            nbands == norbs; when only a subset is stored, nbands < norbs
            (huge mode).
        '''
        self._fname = fnm
        self._lgam = True

        if not Path(fnm).exists():
            raise FileNotFoundError(f"Wavefunction file {fnm} not found.")
        
        self.readWF()

    def isGammaWfc(self):
        return True if self._lgam else False
    
    def readWF(self):
        file = np.load(self._fname)
        eigenvalues = file['eigenvalues'] # shape: (norbitals,)
        self._wfc = file['wfc'] # shape: (nbands, norbitals)

        self._nkpts = 1
        self._nspin = 1
        self._nbands = self._wfc.shape[0]
        self._norbs = self._wfc.shape[1]
        # energy
        self._bands = eigenvalues.reshape(self._nspin, self._nkpts, -1) # shape: (nspin, nkpts, norbitals)
        # huge mode
        self._huge_mode = self._nbands < self._norbs

    def readBandCoeffs(self, iband : slice):
        '''
        Return the NAO expansion coefficients for the specified KS states.

        In huge mode the slice must span exactly ``_nbands`` indices and the
        full ``_wfc`` array is returned regardless of the slice value.

        Parameters
        ----------
        iband : slice
            Band index slice into the first axis of _wfc.

        Returns
        -------
        ndarray, shape (nbands, norbs)
        '''
        if self._huge_mode:
            assert len(range(iband.start, iband.stop, iband.step)) == self._nbands, \
                "In huge mode, the slice length must be equal to nbands!"
            return self._wfc

        else:
            return self._wfc[iband]


    def checkIndex(self, ispin, ikpt, iband):
        '''
        Assert that (ispin, ikpt, iband) are all 1-based valid indices.
        '''
        assert 1 <= ispin <= self._nspin,  'Invalid spin index!'
        assert 1 <= ikpt <= self._nkpts,  'Invalid kpoint index!'
        assert 1 <= iband <= self._nbands, 'Invalid band index!'
