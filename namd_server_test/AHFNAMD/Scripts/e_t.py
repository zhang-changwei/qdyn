import matplotlib as mpl
mpl.use('agg')
mpl.rcParams['axes.unicode_minus'] = False

import matplotlib.pyplot as plt
import numpy as np

fig = plt.figure()
ax  = plt.subplot()

Enr = np.loadtxt("EIGTXT")
Y = np.diff(Enr, axis = 0)
np.savetxt("deltaE.txt", Y)
VB = Y[:,0]
CB = Y[:,1]
time = np.arange(np.size(VB))
line, = ax.plot(time, VB, label='VB')
line, = ax.plot(time, CB, label='CB')

ax.set_xlabel('Time [fs]', labelpad=5)
ax.set_ylabel('$delta$E', labelpad=5)

ax.legend()

plt.tight_layout(pad=0.2)
plt.savefig('deltaEnr.png', dpi=720)
