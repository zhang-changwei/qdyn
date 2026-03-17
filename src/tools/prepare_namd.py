import os
from pathlib import Path
from typing import List, Dict, Any

import numpy as np
import numpy.typing as npt
from jobflow import job

from ..input import PreNAMDInputT
from .canac import extract_eigvals_and_nacs
from .dephase import calculate_dephasing_time


@job
def run_pre_namd(
    software: str,
    parameters: PreNAMDInputT,
    scf_batch_results: List[Dict],
    prev_output: Dict[str, Any],
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
    scf_batch_results : List[Dict]
        List of SCF batch results, each containing:
        - run_dir: Working directory path for the batch task
        - frame_range: (start, end) frame indices
        - vbm: VBM band index
        - cbm: CBM band index
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
    # No input files required
    if prepare_input_only:
        return

    # Reconstruct all SCF subdirectories from batch results
    all_scf_dirs = []
    for batch_result in scf_batch_results:
        run_dir = batch_result.get('run_dir', '')
        frame_range = batch_result.get('frame_range', (0, 0))
        frame_start, frame_end = frame_range

        for global_idx in range(frame_start, frame_end + 1):
            subdir_name = f"scf_{global_idx:04d}"
            subdir_path = os.path.join(run_dir, subdir_name)
            all_scf_dirs.append(subdir_path)

    # Sort directories to ensure chronological order
    import natsort

    all_scf_dirs = natsort.natsorted(all_scf_dirs)

    # Find VBM/CBM from any successful batch
    vbm = cbm = 0
    for batch_result in scf_batch_results:
        if batch_result.get('vbm', 0) > 0:
            vbm = batch_result['vbm']
            cbm = batch_result['cbm']
            break

    # If not found in batch results, try prev_output
    if vbm == 0 and 'vbm' in prev_output:
        vbm = prev_output['vbm']
        cbm = prev_output['cbm']

    # basics
    is_gamma_ver = False
    if software == 'vasp':
        with open(f'{run_dirs[0]}/OUTCAR', 'r') as f:
            head = f.readline()
            if head.strip().endswith('gamma-only'):
                is_gamma_ver = True
    elif software in ['abacus', 'hamgnn', 'openmx', 'siesta']:
        is_gamma_ver = True

    # sort dirs
    indices = []
    for run_dir in run_dirs:
        idx = int(Path(run_dir).name)
        indices.append(idx)
    sorted_indices = np.argsort(indices)
    run_dirs = [run_dirs[i] for i in sorted_indices]

    if isinstance(parameters.bmin, str):
        bmin_ = parameters.bmin.lower()
        bmin_ = bmin_.replace('vbm', str(vbm))
        bmin_ = bmin_.replace('cbm', str(cbm))
        bmin_ = eval(bmin_)
    else:
        bmin_ = parameters.bmin
    if isinstance(parameters.bmax, str):
        bmax_ = parameters.bmax.lower()
        bmax_ = bmax_.replace('vbm', str(vbm))
        bmax_ = bmax_.replace('cbm', str(cbm))
        bmax_ = eval(bmax_)
    else:
        bmax_ = parameters.bmax

    extract_eigvals_and_nacs(
        run_dirs=run_dirs,
        software=software,  # type: ignore
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

    images = []
    if plot:
        pass

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
        'software': software,
        'images': images,
        'EIGTXT': str(Path.cwd() / 'EIGTXT'),
        'NATXT': str(Path.cwd() / 'NATXT'),
        'DEPHTIME': (
            str(Path.cwd() / 'DEPHTIME')
            if parameters.surface_hopping == 'DISH'
            else None
        ),
    }
