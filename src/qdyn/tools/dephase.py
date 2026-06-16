#!/usr/bin/env python

import os
from pathlib import Path
import numpy as np
import numpy.typing as npt
from scipy.optimize import curve_fit
from scipy.integrate import cumulative_trapezoid
from scipy.fftpack import fft

from typing import Any


def calculate_dephasing_time(
    energies: npt.NDArray[np.float64],
    md_dt: float = 1.0,
    plot: bool = False,
) -> dict[str, Any]:
    r"""Calculate pairwise dephasing times from KS energy eigenvalue trajectories.

    Args:
        working_dir: Directory where output files and optional plots are written.
        energies: Array of KS energies in eV with shape ``(nstep, nbasis)``.
        md_dt: MD time step in femtoseconds used to set the time axis.
            Default 1.0 fs.
        plot: If ``True``, save a ``dephasing_i_j.png`` plot of ``D(t)``
            for every state pair to *working_dir*.

    Returns:
        dict: Mapping with ``DEPHTIME`` and generated image paths.
    """

    nbasis = energies.shape[1]
    matrix = np.zeros((nbasis, nbasis), dtype=np.float64)
    images = []

    working_dir = str(Path.cwd())
    if plot:
        os.makedirs("figs_dephasing", exist_ok=True)
        handle = plot_dephasing_time()
        next(handle)

    for ii in range(nbasis):
        for jj in range(ii):
            Et = energies[:, ii] - energies[:, jj]
            T = np.arange(Et.size) * md_dt

            Ct, Dt, Iw = dephase(Et)

            try:
                popt, pcov = curve_fit(gaussian, T, Dt)
            except Exception as exc:
                matrix[ii, jj] = -1.
                matrix[jj, ii] = -1.
            else:
                Dt_fit = gaussian(T, *popt)
                matrix[ii, jj] = popt[0]
                matrix[jj, ii] = matrix[ii, jj]

                if plot:
                    fig_path = f'{working_dir}/figs_dephasing/dephasing_{ii}_{jj}.png'
                    handle.send( # type: ignore
                        (False, fig_path, T, Dt)
                    )
                    images.append(fig_path)

    # output
    deph_path = f'{working_dir}/DEPHTIME'
    np.savetxt(deph_path, matrix, fmt='%10.4f')

    return {'DEPHTIME': deph_path, 'images': images}


def gaussian(x, sigma):
    return np.exp(-(x**2) / (2 * sigma**2))


def dephase(
    Et, dt=1.0
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], npt.NDArray[np.float64]]:
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

    hbar = 0.6582119513926019  # eV fs

    Et = np.asarray(Et)
    Et -= np.mean(Et)

    # Autocorrelation Function (ACF) of Et
    Ct = np.correlate(Et, Et, 'full')[Et.size - 1 :] / Et.size

    # Cumulative integration of the ACF
    Gt = cumulative_trapezoid(
        cumulative_trapezoid(Ct, dx=dt, initial=0), dx=dt, initial=0
    )
    Gt /= hbar**2
    # Dephasing function
    Dt = np.exp(-Gt)

    # FT of normalized ACF
    Iw = np.abs(fft(Ct / Ct[0])) ** 2

    return Ct, Dt, Iw


def plot_dephasing_time():
    import matplotlib
    import matplotlib.pyplot as plt
    matplotlib.use('agg')

    fig = plt.figure(figsize=(4.8, 3.0))
    ax = plt.subplot()

    while True:
        close, fig_path, T, Dt = yield
        if close:
            break
        N = min(len(T), len(Dt))
        ax.cla()
        ax.plot(T[:N], Dt[:N], ls='-', lw=1.0)
        ax.set_xlabel('Time (fs)')
        ax.set_ylabel('Dephasing function')
        fig.tight_layout()
        fig.savefig(fig_path, transparent=True, dpi=300)
