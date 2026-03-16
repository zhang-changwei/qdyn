from glob import glob
from pathlib import Path
import shutil
import subprocess

import matplotlib as mpl
from matplotlib import pyplot as plt
from mpl_toolkits.axes_grid1 import make_axes_locatable
import numpy as np
import numpy.typing as npt
from jobflow import job

from ..input import NAMDInputT

@job
def run_namd(
    parameters: NAMDInputT,
    eigtxt: str,
    natxt: str,
    dephtime: str | None,
    nodes: int,
    ntasks_per_node: int,
    cpus_per_task: int,
    plot: bool = False,
    prepare_input_only: bool = False,
):
    sh = parameters.surface_hopping
    eigenvalues = np.loadtxt(eigtxt)
    nsw, nbasis = eigenvalues.shape
    
    # Prepare input files for NAMD
    shutil.copy(eigtxt, 'EIGTXT')
    shutil.copy(natxt, 'NATXT')
    if sh == 'DISH' and dephtime is not None:
        shutil.copy(dephtime, 'DEPHTIME')

    time_start = 2
    time_stop = nsw - parameters.namdtime - 1 if sh == 'FSSH' else nsw - 1
    assert time_stop > time_start, "Not enough time steps for the specified namdtime."
    inicon = sample_initial_conditions(
        time_start,
        time_stop,
        bmin=1001,
        bmax=1000 + nbasis,
        nsample=parameters.nsample,
    )
    np.savetxt('INICON', inicon, fmt='%d')

    inp = _parepare_namd_input(parameters, nodes, nbasis, nsw)
    with open('inp', 'w') as f:
        f.write(inp)

    if prepare_input_only:
        return {
            'run_dir': str(Path.cwd()),
            'images': [],
        }

    # run namd
    if sh == 'FSSH':
        subprocess.run(['hfnamd'])
    else:
        subprocess.run(['mpirun', '-np', str(nodes * ntasks_per_node), 'hfnamd'])

    # plot
    images = []
    if plot:
        if sh == 'FSSH':
            out = plot_fssh(eigenvalues, lhole=parameters.lhole)
            images.extend(out['images'])
        else:
            out = plot_dish(nbasis, parameters.md_dt)
            images.extend(out['images'])

    return {
        'run_dir': str(Path.cwd()),
        'images': images,
    }
    


def sample_initial_conditions(
    time_start: int,
    time_stop: int,
    bmin: int,
    bmax: int,
    nsample: int = 200,
) -> npt.NDArray[np.int32]:
    rng = np.random.default_rng()
    inicon = np.zeros([nsample, 2], dtype=np.int32)
    inicon[:, 0] = rng.integers(time_start, time_stop, size=nsample, endpoint=True)
    inicon[:, 1] = rng.integers(bmin, bmax, size=nsample, endpoint=True)
    return inicon

def _parepare_namd_input(
    parameters: NAMDInputT,
    nodes: int,
    nbasis: int,
    nsw: int,
):
    inp = rf'''
&NAMDPARA
    NPAR       = {nodes}

    BMIN       = 1001
    BMAX       = {1000 + nbasis}
    
    NSAMPLE    = {parameters.nsample}
    NTRAJ      = {parameters.ntraj}
    NSW        = {nsw}
    NELM       = {parameters.nelm}

    TEMP       = {parameters.temperature}
    NAMDTIME   = {parameters.namdtime}
    POTIM      = {parameters.md_dt}

    ALGO       = "{parameters.surface_hopping}"
    ALGO_INT   = 0
    LHOLE      = {".TRUE." if parameters.lhole else ".FALSE."}
    LSHP       = .TRUE.
    LBINOUT    = {".TRUE." if parameters.surface_hopping == "DISH" 
                  else ".FALSE."}
    LCPTXT     = .TRUE.

    DEBUGLEVEL = "I"
/
'''
    return inp

def plot_fssh(energies: npt.NDArray, lhole: bool = False):
    nbasis, nsw = energies.shape
    f_shprop = glob('SHPROP.*')
    data = np.array(np.loadtxt(f) for f in f_shprop)
    data = np.mean(data, axis=0)

    shprop = data[:, 2:] # shape (namdtime, nbasis)
    time = data[:, 0]
    avg_energy = data[:, 1]
    namdtime = shprop.shape[0]

    ens = np.zeros([namdtime, nbasis], dtype=np.float64)
    ini_times = [int(f.split('.')[-1]) for f in f_shprop]
    for start in ini_times:
        stop = start + namdtime
        ens += energies[start - 1: stop]
    ens /= len(ini_times)

    np.savez('fssh.npz', 
             time=time, avg_energy=avg_energy, shprop=shprop, ens=ens)

    # plot energy relaxation
    mpl.use('agg')
    mpl.rcParams['axes.unicode_minus'] = False
    plt.clf()
    fig = plt.figure(figsize=(4.8, 3.0))
    ax  = plt.subplot()
    divider = make_axes_locatable(ax)
    ax_cbar = divider.append_axes('right', size="5%", pad=0.02)

    ax.plot(time, avg_energy, '--', color='blue', lw=1.5, alpha=0.6,
            label=f'Average {"Hole" if lhole else "Electron"} Energy')
    kmap = ax.scatter(time, ens, c=shprop, cmap='hot_r', vmin=0, vmax=1,
                      s=15, alpha=0.8, lw=0)
    plt.colorbar(kmap, cax=ax_cbar, orientation='vertical',
                 ticks=np.linspace(0, 1, 6, endpoint=True))
    ax.legend(fancybox=False, framealpha=0.7, fontsize=9)

    ax.set_xlim(0, time[-1])
    ax.set_xlabel('Time (fs)', fontsize='small', labelpad=5)
    ax.set_ylabel('Energy (eV)', fontsize='small', labelpad=5)

    plt.tight_layout(pad=0.2)
    plt.savefig('fssh_energy_relaxation.png', dpi=300)

    # plot population evolution
    fig.clf()
    ax = plt.subplot()
    for i in range(len(nbasis)):
        ax.plot(time, shprop[:, i])

    ax.set_xlim(0, time[-1])
    ax.set_ylim(0, 1)
    ax.set_xlabel('Time (fs)', fontsize='small', labelpad=5)
    ax.set_ylabel('Population', fontsize='small', labelpad=5)

    plt.tight_layout(pad=0.2)
    plt.savefig('fssh_population_evolution.png', dpi=300)
    
    return {
        'images': [str(Path.cwd() / 'fssh_energy_relaxation.png'),
                   str(Path.cwd() / 'fssh_population_evolution.png')],
    }

def plot_dish(nbasis: int, md_dt: float):
    f_shprop = glob('SHPROP.*')

    data = np.fromfile(f_shprop[0]).reshape(-1, nbasis)[::100]
    for idx, f in enumerate(f_shprop[1:]):
        data += np.fromfile(f).reshape(-1, nbasis)[::100]
    data /= len(f_shprop)
    namdtime = data.shape[0]
    time = np.arange(namdtime) * md_dt * 0.1 # ps

    np.savez('dish.npz', time=time, shprop=data)

    # plot population evolution
    mpl.use('agg')
    mpl.rcParams['axes.unicode_minus'] = False
    plt.clf()
    fig = plt.figure(figsize=(4.8, 3.0))
    ax  = plt.subplot()
    for i in range(nbasis):
        ax.plot(time, data[:, i])

    ax.set_xlim(0, time[-1])
    ax.set_ylim(0, 1)
    ax.set_xlabel('Time (ps)', fontsize='small', labelpad=5)
    ax.set_ylabel('Population', fontsize='small', labelpad=5)

    plt.tight_layout(pad=0.2)
    plt.savefig('dish_population_evolution.png', dpi=300)

    return {
        'images': [str(Path.cwd() / 'dish_population_evolution.png')],
    }
