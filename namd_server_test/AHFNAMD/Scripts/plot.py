import os
import numpy as np
import matplotlib as mpl
mpl.use('agg')
mpl.rcParams['axes.unicode_minus'] = False

import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from mpl_toolkits.axes_grid1 import make_axes_locatable

if not os.path.exists('w.txt'):
    w1= np.loadtxt('pyband_weights_component_1.dat')
    w2= np.loadtxt('pyband_weights_component_2.dat')
    w = w1/(w1+w2)
    w = np.nan_to_num(w, nan=0.5)
    np.savetxt('w.txt', w)

dat = np.loadtxt('pyband.dat')
Wht = np.loadtxt('w.txt')
nband = dat.shape[1] - 1
x = dat[:,0]
fig = plt.figure()
fig.set_size_inches(4.8, 3.0)

########################################
ax      = plt.subplot()
LW    = 1.0
DELTA = 0.3
norm  = mpl.colors.Normalize(vmin=Wht.min(),
                             vmax=Wht.max())
# create a ScalarMappable and initialize a data structure
s_m   = mpl.cm.ScalarMappable(cmap='seismic', norm=norm)
s_m.set_array([Wht])

for iband in range(nband):
# for iband in range(280, 300):
    print('Processing band: {:4d}...'.format(iband))
    y = dat[:,iband+1]
    z = Wht[:,iband+1]

    ax.plot(x, y,
            lw=LW + 2 * DELTA,
            color='gray', zorder=1)

    points = np.array([x, y]).T.reshape(-1, 1, 2)
    segments = np.concatenate([points[:-1], points[1:]], axis=1)
    lc = LineCollection(segments,
                        colors=[s_m.to_rgba(ww) for ww in (z[1:] + z[:-1])/2.]
                        )
    # lc.set_array((z[1:] + z[:-1]) / 2)
    lc.set_linewidth(LW)
    ax.add_collection(lc)

    divider = make_axes_locatable(ax)
    ax_cbar = divider.append_axes('right', size='5%', pad=0.02)
    cbar = plt.colorbar(s_m, cax=ax_cbar,
                        # ticks=[Wht.min(), Wht.max()],
                        orientation='vertical')
    cbar.set_ticks([Wht.max(), Wht.min()])
    cbar.set_ticklabels(["down", "up"])

#ax.set_xlim(0,59)
ax.set_ylim(-3.0, 7.0)

ax.axvline(x[19], lw=0.5, c='0')
ax.axvline(x[39], lw=0.5, c='0')
ax.set_xticks([x[0], x[19], x[39], x[59]])
ax.set_xticklabels([r'$\Gamma$', 'M', 'K', r'$\Gamma$'])
ax.set_ylabel('Energy [eV]', fontsize=None, labelpad=8)
ax.tick_params(which='both', labelsize='x-small')

########################################
plt.tight_layout(pad=0.2)
plt.savefig('pband.png', dpi=360)
