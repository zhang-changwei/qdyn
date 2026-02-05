#/usr/bin/env python
from vaspwfc import vaspwfc
import os
pswfc = vaspwfc('WAVECAR', lgamma=True)
# KS orbital in real space, double the size of the FT grid
phi = pswfc.get_ps_wfc(ikpt=1, iband=936, ngrid=pswfc._ngrid * 2)
phi2 = pswfc.get_ps_wfc(ikpt=1, iband=937, ngrid=pswfc._ngrid * 2)
# Save the orbital into files. Since the wavefunction consist of complex
# numbers, the real and imaginary part are saved separately.
pswfc.save2vesta(phi, poscar='POSCAR')
os.rename("wfc_r.vasp", "936wfc_r.vasp")
#os.rename("wfc_i.vasp", "936wfc_i.vasp")
pswfc.save2vesta(phi2, poscar='POSCAR')
os.rename("wfc_r.vasp", "937wfc_r.vasp")
#os.rename("wfc_i.vasp", "937wfc_i.vasp")
