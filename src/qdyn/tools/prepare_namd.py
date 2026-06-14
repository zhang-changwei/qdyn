import os
from pathlib import Path
import shutil
from typing import List, Dict, Tuple, Any

import numpy as np
from jobflow.core.job import job

from ..calc_common import parse_band_index
from ..input import PreNAMDInputT
from ..output_postprocess import extract_wht_with_cache, extract_band_edges
from .canac import collect_tdolap_output, extract_nacs
from .dephase import calculate_dephasing_time


@job
def qdyn_pre_namd(
    software: str,
    parameters: PreNAMDInputT,
    run_dirs: List[str],
    nproc: int = 1,
    plot: bool = False,
    prepare_input_only: bool = False,
) -> Dict[str, Any]:
    """Run NAMD preprocessing: extract eigenvalues and NACs from SCF results.

    Args:
        software: Software name.
        parameters: Pre-NAMD parameters.
        run_dirs: List of SCF run directories.
        nproc: Number of processes for parallel calculation.
        plot: Whether to generate plots.
        prepare_input_only: If True, only prepare input files without running.

    Returns:
        Dictionary containing run_dir, software, images, and output file paths.
    """
    software_lower = software.lower()
    # No input files required
    if prepare_input_only:
        return {}

    # Reconstruct all SCF subdirectories from batch results
    # Subdirectories may have different naming patterns but always contain digits (e.g., 001, 0001, 0250)
    all_scf_dirs = []
    for run_dir in run_dirs:
        # Find all scf_* subdirectories
        for entry in Path(run_dir).glob('scf_*'):
            if entry.is_dir():
                all_scf_dirs.append(entry)
        # Find resume file
        for entry in Path(run_dir).glob("tdolap_nstep=*.npz"):
            if entry.is_file():
                fname = entry.name
                shutil.copy2(entry, Path.cwd() / fname)

    if len(all_scf_dirs) == 0:
        raise IndexError(
            f"No scf_* directories found in {run_dirs}. "
            "Please check the directory structure."
        )

    # Sort directories by scf index to ensure chronological order
    # (different batches may have different run_dir UUIDs)
    all_scf_dirs.sort(key=lambda x: int(os.path.basename(x).split('scf_')[-1]))

    vbm, cbm, nbands = extract_band_edges(
        software=software_lower,
        dir_path=all_scf_dirs[0],
        whichk=parameters.adv.ikpt,
        whichs=parameters.adv.ispin,
    )
    images = []
    if plot:
        ksen_path = plot_ksen_weight(
            software_lower, all_scf_dirs, parameters, vbm, cbm, nproc
        )
        images.append(ksen_path)

    # basics
    is_gamma_ver = False
    if software_lower == 'vasp':
        with open(f'{all_scf_dirs[0]}/OUTCAR', 'r') as f:
            head = f.readline()
            if head.strip().endswith('gamma-only'):
                is_gamma_ver = True
    elif software_lower in ['abacus', 'hamgnn', 'openmx', 'siesta']:
        is_gamma_ver = True

    bmin = parse_band_index(parameters.bmin, vbm, nbands)
    bmax = parse_band_index(parameters.bmax, vbm, nbands)

    out_traj = collect_tdolap_output(
        run_dirs=all_scf_dirs,
        software=software_lower,  # type: ignore
        is_gamma_ver=is_gamma_ver,
        is_alle=parameters.adv.alle,
        bmin=bmin,
        bmax=bmax,
        ikpt=parameters.adv.ikpt,
        ispin=parameters.adv.ispin,
        nproc=nproc,
        dirs_sorted=True,
    )

    tdolap_link = Path(run_dirs[0]) / Path(out_traj['tdolap_path']).name
    if tdolap_link.exists() or tdolap_link.is_symlink():
        tdolap_link.unlink()
    tdolap_link.symlink_to(Path(out_traj['tdolap_path']).resolve())

    tdolap_data = np.load(out_traj['tdolap_path'])
    out_nac = extract_nacs(
        data=tdolap_data,
        tdolap_path=out_traj['tdolap_path'],
        nproc=nproc,
    )

    # DEPHTIME
    if parameters.surface_hopping == 'DISH':
        output = calculate_dephasing_time(
            energies=out_nac['eigenvalues'],
            md_dt=parameters.md_dt,
            plot=plot,
        )
        images.extend(output.get('images', []))

    return {
        'run_dir': str(Path.cwd()),
        'software': software_lower,
        'images': images[:10], # Only return the first 10 images to avoid overflow
        'VBM': vbm,
        'CBM': cbm,
        'traj_path': out_traj['tdolap_path'],
        'nac_path': out_nac['nac_path'],
        'deph_path': (
            str(Path.cwd() / 'DEPHTIME')
            if parameters.surface_hopping == 'DISH'
            else None
        ),
    }


def plot_ksen_weight(
    software: str,
    run_dirs: list,
    parameters: PreNAMDInputT,
    vbm: int,
    cbm: int,
    nproc: int | None = None,
    filename: str = 'ksen_wht.png',
    cmap: str = 'seismic',
    figsize: Tuple[float, float] = (4.8, 3.0),
    dpi: int = 360,
) -> str:
    """Plot Kohn-Sham energy bands with weight coloring.

    This function creates a scatter plot of energy bands over time,
    where the color represents the weight (e.g., atomic projection).

    Args:
        software: Software name: 'vasp', 'cp2k', 'siesta', 'abacus',
            'openmx'.
        run_dirs: List of directories to process.
        parameters: Pre-NAMD input parameters containing:
            - md_dt: time step in fs
            - adv.ispin: spin index (1-based, converted to 0-based internally)
            - adv.ikpt: k-point index (1-based, converted to 0-based internally)
        nproc: Number of parallel processes. If None, uses all available CPUs.
        filename: Output filename for the plot (default: 'ksen_wht.png').
        cmap: Colormap name (default: 'seismic').
        figsize: Figure size in inches (default: (4.8, 3.0)).
        dpi: Output DPI (default: 360).

    Returns:
        Path to the saved plot.
    """
    
    if software in ['abacus', 'openmx', 'hamgnn']:
        return ''
    
    import matplotlib
    matplotlib.use('agg')
    import matplotlib.pyplot as plt
    from mpl_toolkits.axes_grid1 import make_axes_locatable

    # Extract parameters
    dt = parameters.md_dt
    which_spin = parameters.adv.ispin # 1-based
    which_kpoint = parameters.adv.ikpt # 1-based
    which_atoms = parameters.adv.which_atoms
    if which_atoms is not None:
        which_atoms = np.asarray(which_atoms, dtype=int)
        if which_atoms.ndim != 1 or which_atoms.size == 0:
            raise ValueError(
                f"which_atoms must be a non-empty 1D array, got shape {which_atoms.shape}."
            )
        if np.any(which_atoms <= 0):
            raise ValueError(
                f"which_atoms must use 1-based atom indices, got {which_atoms.tolist()}."
            )
        which_atoms = which_atoms - 1
    cbar_labels = parameters.adv.cbar_labels

    # Extract energy and weight data
    Enr, Wht = extract_wht_with_cache(
        software=software,
        run_dirs=run_dirs,
        which_spin=which_spin,
        which_kpoint=which_kpoint,
        which_atoms=which_atoms,
        nproc=nproc,
    )

    if Enr.ndim != 2 or Wht.ndim != 2:
        raise ValueError(
            f"Expected Enr/Wht to be 2D arrays after spin/k-point selection, got {Enr.shape} and {Wht.shape}."
        )
    if Enr.shape != Wht.shape:
        raise ValueError(
            f"Enr and Wht must have the same shape, got {Enr.shape} and {Wht.shape}."
        )
    if Enr.size == 0:
        raise ValueError("Enr/Wht is empty; cannot generate KS energy-weight plot.")

    # Derive dimensions from array shapes
    nsw, nband = Enr.shape

    # Create a time grid with the exact same shape as Enr/Wht for scatter().
    T = np.broadcast_to((np.arange(nsw, dtype=float) * dt)[:, np.newaxis], (nsw, nband))

    vbm_idx = vbm -1
    cbm_idx = cbm -1

    # Create figure
    fig = plt.figure()
    fig.set_size_inches(*figsize)

    ax = plt.subplot()

    # Scatter plot with weight coloring
    img = ax.scatter(
        T.ravel(),
        Enr.ravel(),
        s=1.0,
        c=Wht.ravel(),
        lw=0.0,
        zorder=1,
        vmin=Wht.min(),
        vmax=Wht.max(),
        cmap=cmap,
    )

    # Add colorbar
    divider = make_axes_locatable(ax)
    ax_cbar = divider.append_axes('right', size='5%', pad=0.02)
    cbar = plt.colorbar(img, cax=ax_cbar, orientation='vertical')

    if cbar_labels is not None:
        if len(cbar_labels) != 2:
            raise ValueError(
                f"cbar_labels must contain exactly 2 labels, got {len(cbar_labels)}."
            )
        cbar.set_ticks([Wht.max(), Wht.min()])
        cbar.set_ticklabels(cbar_labels)

    # Set energy limits
    ymin = min(Enr[0, vbm_idx], Enr[0, cbm_idx]) - 0.5
    ymax = max(Enr[0, vbm_idx], Enr[0, cbm_idx]) + 0.5
    ax.set_ylim(ymin, ymax)

    # Labels and formatting
    ax.set_xlabel('Time [fs]', labelpad=5)
    ax.set_ylabel('Energy [eV]', labelpad=8)
    ax.tick_params(which='both', labelsize='x-small')

    plt.tight_layout(pad=0.2)
    plt.savefig(filename, dpi=dpi)
    plt.close()

    return os.path.abspath(filename)
