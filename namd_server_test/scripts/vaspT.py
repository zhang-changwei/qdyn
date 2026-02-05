import matplotlib as mpl
mpl.use('agg')
mpl.rcParams['axes.unicode_minus'] = False

import matplotlib.pyplot as plt
import subprocess
import os

def vaspT():
    if not os.path.isfile('OSZICAR'):
        return 1
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

def plot_data(filename):
    steps = []
    temperatures = []
    total_energies = []
    E_pots = []
    E_kins = []

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

# Assuming the data is written to '.vasp_md.dat'
if not os.path.isfile('md_vasp.dat'):
    vaspT()
plot_data('md_vasp.dat')
