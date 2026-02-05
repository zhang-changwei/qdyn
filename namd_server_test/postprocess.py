import re
import numpy as np
import matplotlib as mpl
mpl.use('agg')

import matplotlib.pyplot as plt
from os.path import isfile
import subprocess
import os
import logging
from config import BASE_DIR

def check_md_convergence(nsw, max_unconverged, slurm_id=None):
    if slurm_id:
        slurm_file = f"slurm-{slurm_id}.out"
        if not os.path.isfile(slurm_file):
            logging.error(f"Slurm file {slurm_file} not found in the current directory.")
            raise RuntimeError(f"Slurm file {slurm_file} not found in the current directory.")
        latest_slurm_file = slurm_file
    else:
        slurm_files = [f for f in os.listdir('.') if f.startswith('slurm-') and f.endswith('.out')]
        if not slurm_files:
            logging.error("No slurm output files found in the current directory.")
            raise RuntimeError("No slurm output files found in the current directory.")
        latest_slurm_file = max(slurm_files, key=os.path.getmtime)
    
    logging.info(f"Checking file: {latest_slurm_file}")

    with open(latest_slurm_file, 'r') as f:
        lines = f.readlines()
        nsw_line = []
        error_line = []
        for i, line in enumerate(lines):
            if 'T= ' in line:
                nsw_line.append(i)
            elif 'self-consistency was not achieved' in line:
                error_line.append(i)
    
    if not error_line:
        logging.info("No self-consistency errors found.")
        return True    
    if error_line[-1] < nsw_line[-nsw] and len(error_line) <= max_unconverged:
        logging.info(f"MD converged successfully in the last {nsw} steps.")
        return True
    else:
        logging.error(f"MD did not converge in the last {nsw} steps. Please check {latest_slurm_file} for details.")
        return False
    
def vaspT():
    if os.path.isfile('INCAR'):
        potim = subprocess.check_output("grep POTIM INCAR | awk '{print $3}'", shell=True).decode().strip()
    else:
        potim = '1'
    with open('md_vasp.dat', 'w') as f:
        f.write(f"# Time step: {potim}\n")
        f.write("# Step  Temperature Total_energy E_pot E_kin\n")
        with open('OSZICAR', 'r') as oszicar:
            Tsum = 0
            Ns = 0
            for line in oszicar:
                if 'T=' in line:
                    values = line.split()
                    T = float(values[2])
                    E_total = float(values[8]) + float(values[10])
                    E_pot = float(values[8])
                    E_kin = float(values[10])
                    f.write(f"{values[0]} {T:8.1f} {E_total:12.6f} {E_pot:12.6f} {E_kin:12.6f}\n")
                    Tsum += T
                    Ns += 1
            f.write(f"# {Ns} {Tsum/Ns}\n")

def plot_nvt():
    steps = []
    temperatures = []
    total_energies = []
    E_pots = []
    E_kins = []
    
    if not os.path.isfile('md_vasp.dat'):
        vaspT()
    filename = 'md_vasp.dat'
    
    with open(filename, 'r') as file:
        for line in file:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split()
            steps.append(int(parts[0]))
            temperatures.append(float(parts[1]))
            total_energies.append(float(parts[2]))
            E_pots.append(float(parts[3]))
            E_kins.append(float(parts[4]))

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(8, 12))

    # Plot temperatures
    ax1.set_xlabel('Step')
    ax1.set_ylabel('Temperature')
    ax1.plot(steps, temperatures, color='tab:red')

    # Plot E_pots
    ax2.set_xlabel('Step')
    ax2.set_ylabel('E_pot')
    ax2.plot(steps, E_pots, color='tab:green')

    # Plot total_energies
    ax3.set_xlabel('Step')
    ax3.set_ylabel('Total Energy')
    ax3.plot(steps, total_energies, color='tab:blue')

    fig.tight_layout()

    # Save the figure
    plt.savefig('T_plots.png')

    return temperatures

def extract_from_vasp_outcar (outFile = 'OUTCAR', whichK=1, whichS=1):
    # outFile = 'OUTCAR'

    OUTCAR = [line for line in open(outFile, 'r') if line.strip()]
    for line in OUTCAR:
        if 'NBANDS' in line and 'NKPTS' in line:
            NBANDS = int(line.split()[-1])
            NKPTS  = int(line.split()[ 3])
        if 'ISPIN  =' in line:
            ISPIN = int(line.split()[2])
            break
    print('Number of Spins: %d' % ISPIN)
    print('Number of Bands: %d' % NBANDS)
    print('Number of Kpoints: %d' % NKPTS)

    # where_scf_ends = [ii for ii, line in enumerate(OUTCAR)
    #                 if 'aborting loop because EDIFF' in line]
    # where_Efermi_starts = []

    where_scf_ends = []
    where_Efermi_starts = [ii for ii, line in enumerate(OUTCAR)
                           if 'E-fermi :' in line]
    # for ii in where_Efermi_starts:
    #     start = ii
    #     while 'E-fermi' not in OUTCAR[start]:
    #         start -= 1
    #     where_Efermi_starts += [start]

    Niters = len(where_Efermi_starts)
    # TDKSEN = np.zeres((Niters, NBANDS))
    TDKSEN = []
    for it, ii in enumerate(where_Efermi_starts):
        if ISPIN == 1:
            start = ii + 1
            end   = start + (NBANDS + 2) * NKPTS + 1
        else:
            start = ii + 1
            end   = start + ((NBANDS + 2) * NKPTS + 1) * ISPIN + 2

        tmp = [ line.split()[1] for line in OUTCAR[start:end]
                if not re.search('[a-zA-Z]', line) ]
        TDKSEN += [tmp]

    # Find CBM and update CBINDEX in config.py
    for line in OUTCAR[start:end]:
        if not re.search('[a-zA-Z]', line):
            if line.split()[-1].startswith('0.0'):
                CBM = line.split()[0]
                with open('../VBCB', 'w') as f:
                    f.write(f"CBINDEX = {CBM}\n")
                break

    TDKSEN = np.asarray(TDKSEN, dtype=float).reshape((-1, ISPIN, NKPTS, NBANDS))

    assert TDKSEN.shape[0] == Niters
    # np.savetxt('tden.dat', TDKSEN, fmt='%10.4f')

    return TDKSEN[:,whichS-1,whichK-1,:]

################################################################################
def plot_tdks(kpoint=1, spin=1):

    if isfile('tden.npy'):
        TDKS = np.load('tden.npy')
        with open('../VBCB', 'r') as f:
            vbmIndex = int(f.readline().split('=')[1].strip()) - 1
    else:
        # only plot first spin and first k-points
        TDKS = extract_from_vasp_outcar(whichK=kpoint, whichS=spin)
        np.save('tden.npy', TDKS)
        with open('../VBCB', 'r') as f:
            vbmIndex = int(f.readline().split('=')[1].strip()) - 1

    NSW   = TDKS.shape[0]
    NBAND = TDKS.shape[1]
    dt = 1.0
    # omega = 33.35640951981521 * 1E3 * fftfreq(NSW, dt)

    TIME  = np.arange(NSW) * dt
    VBM_energy = np.average(TDKS[:, vbmIndex-1])
    CBM_energy = np.average(TDKS[:, vbmIndex])
    band_gap = CBM_energy - VBM_energy
    TDKS -= VBM_energy
    # Add VBM_energy, CBM_energy and band_gap to VBCB file
    with open('../VBCB', 'a') as f:
        f.write(f'VBM_energy = {VBM_energy}\n')
        f.write(f'CBM_energy = {CBM_energy}\n')
        f.write(f'Band_gap   = {band_gap}\n')

    fig = plt.figure()
    fig.set_size_inches((6.0, 4.0))

    ax = plt.subplot(111)

    for ii in range(NBAND):
        ax.plot(TIME, TDKS[:,ii], ls='-', lw=1.0, color='b', alpha=0.7)

    # ax.set_xlim(TIME.max() - 2000, TIME.max())
    ax.set_ylim(-0.5*band_gap, 1.5*band_gap)

    plt.tight_layout()
    plt.savefig('tdks.png', dpi=360)