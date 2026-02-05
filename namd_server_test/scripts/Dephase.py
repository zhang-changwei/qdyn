#!/usr/bin/env python

import numpy as np
from scipy.interpolate import interp1d
from scipy.optimize import curve_fit

import matplotlib as mpl
mpl.use('agg')
mpl.rcParams['axes.unicode_minus'] = False
import matplotlib.pyplot as plt

def gaussian(x,c):
    return np.exp(-x**2/(2*c**2))

def dephase(Et, dt=1.0):
    '''
    Calculate the autocorrelation function (ACF), dephasing function, and FT of
    ACF.

    The dephasing function was calculated according to the following formula

    G(t) = (1 / hbar**2) \int_0^{t_1} dt_1 \int_0^{t_2} dt_2 <E(t_2)E(0)>
    D(t) = exp(-G(t))

    where Et is the difference of two KS energies in unit of eV, <...> is the
    ACF of the energy difference and the brackets denote canonical averaging.

    Fourier Transform (FT) of the normalized ACF gives the phonon influence
    spectrum, also known as the phonon spectral density.

    I(\omega) \propto | FT(Ct / Ct[0]) |**2

    Jaeger, Heather M., Sean Fischer, and Oleg V. Prezhdo. "Decoherence-induced surface hopping." JCP 137.22 (2012): 22A545.
    '''

    from scipy.integrate import cumtrapz
    from scipy.fftpack import fft

    hbar = 0.6582119513926019       # eV fs

    Et = np.asarray(Et)
    Et -= np.average(Et)

    # Autocorrelation Function (ACF) of Et
    Ct = np.correlate(Et, Et, 'full')[Et.size-1:] / Et.size
    
    # Cumulative integration of the ACF
    Gt = cumtrapz(cumtrapz(Ct, dx=dt, initial=0), dx=dt, initial=0)
    Gt /= hbar**2
    # Dephasing function
    Dt = np.exp(-Gt)

    # FT of normalized ACF
    Iw = np.abs(fft(Ct / Ct[0]))**2

    return Ct, Dt, Iw

energy = np.loadtxt('EIGTXT')
nbasis = energy.shape[1]
matrix = np.zeros((nbasis, nbasis), dtype=float)

dt = 1.0 # fs

allDt = []

for ii in range(nbasis):
    for jj in range(ii):
        Et = energy[:, ii] - energy[:, jj]
        T = np.arange(Et.size) * dt

        Ct, Dt, Iw = dephase(Et)
        
        if jj == 0:
            N = min(T.size, Dt.size)
            plt.plot(T[:N], Dt[:N], ls='-', lw=1.0)
        
        popt, pcov = curve_fit(gaussian, T, Dt)
        Dt_fit = gaussian(T, *popt)
        matrix[ii,jj] =  popt[0]
        matrix[jj,ii] =  matrix[ii,jj]

plt.xlim(0,100)
plt.savefig('Dt.png')
np.savetxt('DEPHTIME', matrix, fmt='%10.4f')
