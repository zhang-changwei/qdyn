import os, re
import numpy as np
from glob import glob

is_hole  = False
NAMDTIME = 10000000
NSAMPLE  = 50
# potim    = 1.0
inpFiles = glob('SHPROP.*')

if not os.path.isfile('pop.npy'):

    iniTimes = [int(F.split('.')[-1]) for F in inpFiles]
#   dat = np.array([np.loadtxt(F) for F in inpFiles])    #txt files
    dat = np.array([np.fromfile(F) for F in inpFiles]).reshape(NSAMPLE, NAMDTIME, -1) # the initial population of 4th row is 1
    dat = np.average(dat, axis=0)
    np.save('pop.npy', dat)

else:
    dat = np.load('pop.npy')

import matplotlib as mpl
mpl.use('agg')
mpl.rcParams['axes.unicode_minus'] = False

import matplotlib.pyplot as plt

fig = plt.figure()
fig.set_size_inches(4.8, 3.0)

ax  = plt.subplot()

# pop = dat[:, 3]
if is_hole:
    pop = np.sum(dat[:, :-1], axis=1)
else:
    pop = np.sum(dat[:, 1:], axis=1)
# enr = np.sum(dat[:,1]) 

namdtime = np.arange(np.size(pop))/1e6
line, = ax.plot(namdtime, pop, ls='-')

ax.set_xlim(0, np.size(namdtime)/1e6)
# ax.set_ylim(0.95, 1.0)

ax.set_xlabel('Time [ns]', labelpad=5)
ax.set_ylabel('Population', labelpad=5)

# ax.legend()

plt.tight_layout(pad=0.2)
plt.savefig('A_Recomb.png', dpi=720)
