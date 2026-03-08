#!/usr/bin/env python

import numpy as np
import numpy.typing as npt
from scipy.optimize import curve_fit
from scipy.integrate import cumulative_trapezoid
from scipy.fftpack import fft
import matplotlib as mpl
import matplotlib.pyplot as plt
from jobflow import job

from typing import Tuple, Dict
from .output import Output

# mpl.use('agg')
# mpl.rcParams['axes.unicode_minus'] = False

@job
def calculate_dephasing_time(
    working_dir: str,
    energies_path: str = 'EIGTXT',
    md_dt: float = 1.0,
    plot: bool = False,
) -> Output:
    r"""Calculate pairwise dephasing times from KS energy eigenvalue trajectories.

    Parameters
    ----------
    working_dir:
        Directory where output files and optional plots are written.
    energies_path:
        Path to the KS energy file in EIGTXT format: a plain-text array of
        shape ``(nstep, nbasis)`` with energies in eV.
    md_dt:
        MD time step in femtoseconds used to set the time axis.  Default 1.0 fs.
    plot:
        If ``True``, save a ``dephasing_i_j.png`` plot of ``D(t)`` for every
        state pair to *working_dir*.

    Returns
    -------
    Output
        An :class:`~.output.Output` object whose ``files`` list contains the
        path to ``DEPHTIME`` (an ``nbasis × nbasis`` plain-text matrix of
        dephasing times in fs, symmetric with zeros on the diagonal) and whose
        ``images`` list contains the paths to any plots that were generated.
    """

    energy = np.loadtxt(energies_path) # shape (nstep, nbasis)
    nbasis = energy.shape[1]
    matrix = np.zeros((nbasis, nbasis), dtype=np.float64)
    output = Output()

    for ii in range(nbasis):
        for jj in range(ii):
            Et = energy[:, ii] - energy[:, jj]
            T = np.arange(Et.size) * md_dt

            Ct, Dt, Iw = dephase(Et)
            
            if plot:
                N = min(T.size, Dt.size)

                plt.cla()
                ax = plt.subplot(111)
                ax.plot(T[:N], Dt[:N], ls='-', lw=1.0)
                ax.set_xlabel('Time (fs)')
                ax.set_ylabel('Dephasing function')
                plt.tight_layout()
                img_path = f'{working_dir}/dephasing_{ii}_{jj}.png'
                plt.savefig(img_path, dpi=300)

                output.images.append(img_path)
            
            popt, pcov = curve_fit(gaussian, T, Dt)
            Dt_fit = gaussian(T, *popt)
            matrix[ii,jj] = popt[0]
            matrix[jj,ii] = matrix[ii,jj]

    # output
    deph_path = f'{working_dir}/DEPHTIME'
    np.savetxt(deph_path, matrix, fmt='%10.4f')
    output.files.append(deph_path)

    return output


def gaussian(x, sigma):
    return np.exp(-x**2 / (2 * sigma**2))

def dephase(Et, dt = 1.0) -> Tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    r'''
    Calculate the autocorrelation function (ACF), dephasing function, and FT of
    ACF.

    The dephasing function was calculated according to the following formula

    .. math::
        G(t) = (1 / hbar**2) \int_0^{t_1} dt_1 \int_0^{t_2} dt_2 <E(t_2)E(0)>  
        D(t) = exp(-G(t))

    where Et is the difference of two KS energies in unit of eV, <...> is the
    ACF of the energy difference and the brackets denote canonical averaging.

    Fourier Transform (FT) of the normalized ACF gives the phonon influence
    spectrum, also known as the phonon spectral density.

    .. math::
        I(\omega) \propto | FT(Ct / Ct[0]) |**2

    Jaeger, Heather M., Sean Fischer, and Oleg V. Prezhdo. "Decoherence-induced surface hopping." JCP 137.22 (2012): 22A545.
    '''

    hbar = 0.6582119513926019       # eV fs

    Et = np.asarray(Et)
    Et -= np.mean(Et)

    # Autocorrelation Function (ACF) of Et
    Ct = np.correlate(Et, Et, 'full')[Et.size-1:] / Et.size
    
    # Cumulative integration of the ACF
    Gt = cumulative_trapezoid(cumulative_trapezoid(Ct, dx=dt, initial=0), dx=dt, initial=0)
    Gt /= hbar**2
    # Dephasing function
    Dt = np.exp(-Gt)

    # FT of normalized ACF
    Iw = np.abs(fft(Ct / Ct[0]))**2

    return Ct, Dt, Iw
