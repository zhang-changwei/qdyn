import os
from ase.io import read, write

CONFIGS = read('XDATCAR', format='vasp-xdatcar', index=':')

NSW    = len(CONFIGS)               # The number of ionic steps
NSCF   = 2000
NDIGIT = len("{:d}".format(NSCF))   #
PREFIX = '4_SCF/'    # run directories
DFORM  = "/%%0%dd" % NDIGIT         # run dirctories format
for ii in range(NSCF):              # write POSCARs
    p = CONFIGS[ii - NSCF]
    r = (PREFIX + DFORM) % (ii + 1)
    if not os.path.isdir(r): os.makedirs(r)
    write('{:s}/POSCAR'.format(r), p, vasp5=True, direct=True)
