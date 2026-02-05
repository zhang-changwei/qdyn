#!/usr/bin/env python
############################################################
import os, re
import numpy as np
from glob import glob

import matplotlib as mpl
mpl.use('agg')
mpl.rcParams['axes.unicode_minus'] = False

import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from mpl_toolkits.axes_grid1 import make_axes_locatable
############################################################
def WeightFromPro(infile='PROCAR', whichAtom=None, spd=None):
    """
    Contribution of selected atoms to the each KS orbital
    """

    print(infile) 
    assert os.path.isfile(infile), '%s cannot be found!' % infile
    FileContents = [line for line in open(infile) if line.strip()]

    # when the band number is too large, there will be no space between ";" and
    # the actual band number. A bug found by Homlee Guo.
    # Here, #kpts, #bands and #ions are all integers
    nkpts, nbands, nions = [int(xx) for xx in re.sub('[^0-9]', ' ', FileContents[1]).split()]

    if spd:
        Weights = np.asarray([line.split()[1:-1] for line in FileContents
                              if not re.search('[a-zA-Z]', line)], dtype=float)
        Weights = np.sum(Weights[:,spd], axis=1)
    else:
        Weights = np.asarray([line.split()[-1] for line in FileContents
                              if not re.search('[a-zA-Z]', line)], dtype=float)
    
    TotalWeights = np.asarray([line.split()[-1] for line in FileContents
                              if re.search('^tot', line)], dtype=float)

    nspin = Weights.shape[0] // (nkpts * nbands * nions)
    Weights.resize(nspin, nkpts, nbands, nions)
    TotalWeights.resize(nspin, nkpts, nbands)

    Energies = np.asarray([line.split()[-4] for line in FileContents
                            if 'occ.' in line], dtype=float)
    Energies.resize(nspin, nkpts, nbands)
    
    if whichAtom is None:
        return Energies, np.sum(Weights, axis=-1)
    else:
        # whichAtom = [xx - 1 for xx in whichAtom]
        return Energies, np.sum(Weights[:,:,:,whichAtom], axis=-1), TotalWeights

def parallel_wht(runDirs, whichAtoms, nproc=None):
    '''
    calculate localization of some designated in parallel.
    '''
    import multiprocessing
    nproc = multiprocessing.cpu_count() if nproc is None else nproc
    pool = multiprocessing.Pool(processes=nproc)

    results = []
    for rd in runDirs:
        res = pool.apply_async(WeightFromPro, (rd + '/PROCAR', whichAtoms, None,))
        results.append(res)

    enr = []
    wht = []
    if whichAtoms is None:
        for ii in range(len(results)):
            tmp_enr, tmp_wht = results[ii].get()
            enr.append(tmp_enr)
            wht.append(tmp_wht)   
        return np.array(enr), np.array(wht)
    else:    
        totwht = []
        for ii in range(len(results)):
            tmp_enr, tmp_wht, tmp_totwht = results[ii].get()
            enr.append(tmp_enr)
            wht.append(tmp_wht)
            totwht.append(tmp_totwht)
        return np.array(enr), np.array(wht), np.array(totwht)

############################################################
# calculate spatial localization
############################################################
nsw     = 500
num_digits = len("{:d}".format(nsw))
dt      = 1.0
nproc   = 64
prefix  = '4_SCF'
runDirs = [prefix + '/{:0{width}d}'.format(ii + 1, width=num_digits) for ii in range(nsw)]
# which spin, index starting from 0
whichS  = 0
# which k-point, index starting from 0
whichK  = 0 
# which atoms, index starting from 0
#temp    = np.append(np.arange(36), np.arange(36)+72)
whichA  = None
# whichB  = np.append(np.arange(36)+36, np.arange(36)+108)
Alabel  = r'down'
Blabel  = r'up'

if os.path.isfile('all_wht.npy'):
    Wht = np.load('all_wht.npy')
    Enr = np.load('all_en.npy')
else:
    # for gamma point version, no-spin
    if whichA:
        Enr, Wht1, TotWht = parallel_wht(runDirs, whichA, nproc=nproc)
        Enr = Enr[:, whichS,whichK, :]
        Wht1 = Wht1[:, whichS,whichK, :]
        TotWht = TotWht[:, whichS,whichK, :]
        Wht = Wht1 / TotWht
    else:
        Enr, Wht = parallel_wht(runDirs, whichA, nproc=nproc)
        Enr = Enr[:, whichS,whichK, :]
        Wht = Wht[:, whichS,whichK, :]

    # Enr, Wht1 = parallel_wht(runDirs, whichA, nproc=nproc)
    # Enr, Wht2 = parallel_wht(runDirs, whichB, nproc=nproc)
    # Enr = Enr[:, whichS,whichK, :]
    # Wht1 = Wht1[:, whichS,whichK, :]
    # Wht2 = Wht2[:, whichS,whichK, :]
    # Wht = Wht1 / (Wht1 + Wht2)

    np.save('all_wht.npy', Wht)
    np.save('all_en.npy', Enr)

############################################################
fig = plt.figure()
fig.set_size_inches(4.8, 3.0)

########################################
ax      = plt.subplot()
nband   = Enr.shape[1]
T, dump = np.mgrid[0:nsw:dt, 0:nband]
sFac    = 8
############################################################
# METHOD 1.
############################################################
# use scatter to plot the band 
# ax.scatter( T, Enr, s=Wht / Wht.max() * sFac, color='red', lw=0.0, zorder=1)
# for ib in range(nband):
#     ax.plot(T[:,ib], Enr[:,ib], lw=0.5, color='k', alpha=0.5)

############################################################
# METHOD 2.
############################################################
# use colored scatter to plot the band 
img = ax.scatter(T, Enr, s=1.0, c=Wht, lw=0.0, zorder=1,
                 vmin=Wht.min(),
                 vmax=Wht.max(),
                 cmap='seismic')
# for ib in range(280, 300):
#     ax.plot(T[:,ib], Enr[:,ib], c=Wht, lw=0.5, alpha=0.5, zorder=1,
#                 vmin=Wht.min(),
#                 vmax=Wht.max(),
#                 cmap='seismic')

divider = make_axes_locatable(ax)
ax_cbar = divider.append_axes('right', size='5%', pad=0.02)
cbar = plt.colorbar(img, cax=ax_cbar,
                    orientation='vertical')
cbar.set_ticks([Wht.max(), Wht.min()])
cbar.set_ticklabels([Alabel, Blabel])

############################################################
# METHOD 3.
############################################################
# # use color strip to plot the band

# LW    = 1.0
# DELTA = 0.3
# norm  = mpl.colors.Normalize(vmin=Wht.min(),
#                              vmax=Wht.max())
# # create a ScalarMappable and initialize a data structure
# s_m   = mpl.cm.ScalarMappable(cmap='summer', norm=norm)
# s_m.set_array([Wht])

# x     = np.arange(0, nsw, dt)
# # for iband in range(nband):
# for iband in range(280, 300):
#     print('Processing band: {:4d}...'.format(iband))
#     y = Enr[:,iband]
#     z = Wht[:,iband]

#     ax.plot(x, y,
#             lw=LW + 2 * DELTA,
#             color='gray', zorder=1)

#     points = np.array([x, y]).T.reshape(-1, 1, 2)
#     segments = np.concatenate([points[:-1], points[1:]], axis=1)
#     lc = LineCollection(segments,
#                         colors=[s_m.to_rgba(ww) for ww in (z[1:] + z[:-1])/2.]
#                         )
#     # lc.set_array((z[1:] + z[:-1]) / 2)
#     lc.set_linewidth(LW)
#     ax.add_collection(lc)

#     divider = make_axes_locatable(ax)
#     ax_cbar = divider.append_axes('right', size='5%', pad=0.02)
#     cbar = plt.colorbar(s_m, cax=ax_cbar,
#                         # ticks=[Wht.min(), Wht.max()],
#                         orientation='vertical')
#     cbar.set_ticks([Wht.min(), Wht.max()])
#     cbar.set_ticklabels([Alabel, Blabel])

# ax.set_xlim(0, 500)
ax.set_ylim(-2.1955, 0.5367)

ax.set_xlabel('Time [fs]',   fontsize=None, labelpad=5)
ax.set_ylabel('Energy [eV]', fontsize=None, labelpad=8)
ax.tick_params(which='both', labelsize='x-small')

########################################
plt.tight_layout(pad=0.2)
plt.savefig('ksen_wht.png', dpi=360)

