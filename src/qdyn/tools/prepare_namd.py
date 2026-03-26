import ast
import operator
import os
from pathlib import Path
from typing import List, Dict, Tuple, Any, Optional

import matplotlib

matplotlib.use('agg')
import matplotlib.pyplot as plt
import numpy as np
from jobflow import job

from ..input import PreNAMDInputT
from ..output_postprocess import extract_wht_with_cache, extract_band_edges
from .canac import extract_eigvals_and_nacs
from .dephase import calculate_dephasing_time


@job
def qdyn_pre_namd(
    software: str,
    parameters: PreNAMDInputT,
    run_dirs: List[str],
    nproc: int = 1,
    plot: bool = False,
    prepare_input_only: bool = False,
):
    """Run NAMD preprocessing: extract eigenvalues and NACs from SCF results.

    Parameters
    ----------
    software : str
        Software name.
    parameters : PreNAMDInputT
        Pre-NAMD parameters.
    run_dirs : List[str]
        List of SCF run directories.
    nproc : int
        Number of processes for parallel calculation.
    plot : bool
        Whether to generate plots.
    prepare_input_only : bool
        If True, only prepare input files without running.

    Returns
    prev_output : Dict[str, Any]
        Output from previous step (for compatibility).
    nproc : int
        Number of processes for parallel calculation.
    plot : bool
        Whether to generate plots.
    prepare_input_only : bool
        If True, only prepare input files without running.

    Returns
    -------
    Dict
        Dictionary containing run_dir, software, images, and output file paths.
    """
    software_lower = software.lower()
    # No input files required
    if prepare_input_only:
        return

    # Reconstruct all SCF subdirectories from batch results
    # Subdirectories may have different naming patterns but always contain digits (e.g., 001, 0001, 0250)
    all_scf_dirs = []
    for run_dir in run_dirs:
        # Find all scf_* subdirectories
        for entry in Path(run_dir).glob('scf_*'):
            if entry.is_dir():
                all_scf_dirs.append(entry)

    if len(all_scf_dirs) == 0:
        raise IndexError(
            f"No scf_* directories found in {run_dirs}. Please check the directory structure."
        )

    # Sort directories by scf index to ensure chronological order
    # (different batches may have different run_dir UUIDs)
    all_scf_dirs.sort(key=lambda x: int(os.path.basename(x).split('scf_')[-1]))

    vbm, cbm = extract_band_edges(
        software=software_lower,
        dir_path=all_scf_dirs[0],
        whichK=parameters.adv.ikpt,
        whichS=parameters.adv.ispin,
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

    def safe_eval(expr: str) -> Any:
        ALLOWED_OPS = {ast.Add: operator.add, ast.Sub: operator.sub}
        tree = ast.parse(expr, mode='eval')

        def _eval(node):
            if isinstance(node, ast.Constant):
                return node.value
            elif isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_OPS:
                return ALLOWED_OPS[type(node.op)](_eval(node.left), _eval(node.right))
            else:
                raise ValueError(f"Unsupported expression: {expr}")

        return _eval(tree.body)

    if isinstance(parameters.bmin, str):
        bmin_ = parameters.bmin.lower()
        bmin_ = bmin_.replace('vbm', str(vbm))
        bmin_ = bmin_.replace('cbm', str(cbm))
        bmin_ = safe_eval(bmin_)
    else:
        bmin_ = parameters.bmin
    if isinstance(parameters.bmax, str):
        bmax_ = parameters.bmax.lower()
        bmax_ = bmax_.replace('vbm', str(vbm))
        bmax_ = bmax_.replace('cbm', str(cbm))
        bmax_ = safe_eval(bmax_)
    else:
        bmax_ = parameters.bmax

    extract_eigvals_and_nacs(
        run_dirs=all_scf_dirs,
        software=software_lower,  # type: ignore
        is_gamma_ver=is_gamma_ver,
        is_reorder=parameters.adv.reorder,
        is_alle=parameters.adv.alle,
        bmin=bmin_,
        bmax=bmax_,
        ikpt=parameters.adv.ikpt,
        ispin=parameters.adv.ispin,
        nproc=nproc,
        dirs_sorted=True,
    )

    # DEPHTIME
    if parameters.surface_hopping == 'DISH':
        output = calculate_dephasing_time(
            working_dir=Path.cwd(),
            energies_path='EIGTXT',
            md_dt=parameters.md_dt,
            plot=plot,
        )
        images.extend(output.get('images', []))

    return {
        'run_dir': str(Path.cwd()),
        'software': software_lower,
        'images': images,
        'EIGTXT': str(Path.cwd() / 'EIGTXT'),
        'NATXT': str(Path.cwd() / 'NATXT'),
        'DEPHTIME': (
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
    nproc: Optional[int] = None,
    filename: str = 'ksen_wht.png',
    cmap: str = 'seismic',
    figsize: Tuple[float, float] = (4.8, 3.0),
    dpi: int = 360,
) -> str:
    """Plot Kohn-Sham energy bands with weight coloring.

    This function creates a scatter plot of energy bands over time,
    where the color represents the weight (e.g., atomic projection).

    Parameters
    ----------
    software : str
        Software name: 'vasp', 'cp2k', 'siesta', 'abacus', 'openmx'.
    run_dirs : list
        List of directories to process.
    parameters : PreNAMDInputT
        Pre-NAMD input parameters containing:
        - md_dt: time step in fs
        - adv.ispin: spin index (1-based, converted to 0-based internally)
        - adv.ikpt: k-point index (1-based, converted to 0-based internally)
    which_atoms : np.ndarray, optional
        Array of atom indices for which to calculate weights.
    nproc : int, optional
        Number of parallel processes. If None, uses all available CPUs.
    filename : str
        Output filename for the plot (default: 'ksen_wht.png').
    energy_limits : tuple of float, optional
        (ymin, ymax) for energy axis. If None, auto-determined from data.
    cbar_labels : tuple of str, optional
        (max_label, min_label) for colorbar. If None, uses weight values.
    cmap : str
        Colormap name (default: 'seismic').
    figsize : tuple of float
        Figure size in inches (default: (4.8, 3.0)).
    dpi : int
        Output DPI (default: 360).

    Returns
    -------
    str
        Path to the saved plot.
    """
    from mpl_toolkits.axes_grid1 import make_axes_locatable

    # Extract parameters
    dt = parameters.md_dt
    which_spin = parameters.adv.ispin - 1  # Convert to 0-based index
    which_kpoint = parameters.adv.ikpt - 1  # Convert to 0-based index
    which_atoms = parameters.adv.which_atoms
    if which_atoms is not None:
        which_atoms = np.asarray(which_atoms, dtype=int)
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

    # Derive dimensions from array shapes
    nsw = Enr.shape[0]

    # Create time grid using broadcasting (no need for nband)
    # T has shape (nsw, 1), which broadcasts to match Enr shape (nsw, nband)
    T = np.arange(0, nsw * dt, dt)[:, np.newaxis]

    # Create figure
    fig = plt.figure()
    fig.set_size_inches(*figsize)

    ax = plt.subplot()

    # Scatter plot with weight coloring
    img = ax.scatter(
        T,
        Enr,
        s=1.0,
        c=Wht,
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
        cbar.set_ticks([Wht.max(), Wht.min()])
        cbar.set_ticklabels(cbar_labels)

    # Set energy limits
    ax.set_ylim(Enr[0, vbm] - 0.5, Enr[0, cbm] + 0.5)

    # Labels and formatting
    ax.set_xlabel('Time [fs]', labelpad=5)
    ax.set_ylabel('Energy [eV]', labelpad=8)
    ax.tick_params(which='both', labelsize='x-small')

    plt.tight_layout(pad=0.2)
    plt.savefig(filename, dpi=dpi)
    plt.close()

    return os.path.abspath(filename)
