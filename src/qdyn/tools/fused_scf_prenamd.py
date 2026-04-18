import os
import re
import logging
import shutil
from copy import deepcopy
from pathlib import Path
from collections.abc import Generator
from typing import Dict, List, Tuple, Any, TYPE_CHECKING

import matplotlib

matplotlib.use('agg')
import matplotlib.pyplot as plt
import natsort
import numpy as np
import ase.io
from ase import Atoms
from jobflow import job, Job

from ..calc_common import write_stru, read_strus, parse_band_index
from ..input import SCFInputT, PreNAMDInputT
from ..params import chg_name, ipt_files, stru_files
from ..input_prepare import DFTInputs
from ..output_postprocess import extract_band_edges
from .scf import _prepare_scf_input, _validate_scf_output
from .scf import _set_status, STATUS_RUNNING, STATUS_ENDED, STATUS_FAIL
from .canac import extract_tdolaps, extract_nacs
from .dephase import calculate_dephasing_time
from .run_software import run_software

def qdyn_fused_scf_prenamd(
    software: str,
    scf_input: SCFInputT,
    prenamd_input: PreNAMDInputT,
    pp_path: str,
    orb_path: str,
    traj_file_path: str,
    traj_format: str,
    total_cpus: int,
    omp_software: int = 1,
    omp_python: int = 1,
    plot: bool = False,
    prepare_input_only: bool = False,
) -> list[Job]:
    
    batch_size = scf_input.batch_size
    total_frames = scf_input.scf_step

    jobs = []
    outs = []
    
    # Create a job for each batch
    for batch_idx in range(0, total_frames, batch_size):
        batch_end = min(batch_idx + batch_size + 1, total_frames)

        # Global frame indices (0-based)
        frame_start = batch_idx
        frame_end = batch_end

        j = qdyn_fused_scf_prenamd_task(
            software=software,
            scf_input=scf_input,
            prenamd_input=prenamd_input,
            pp_path=pp_path,
            orb_path=orb_path,
            traj_file_path=traj_file_path,
            traj_format=traj_format,
            frame_start=frame_start,
            frame_end=frame_end,
            total_cpus=total_cpus,
            omp_software=omp_software,
            omp_python=omp_python,
            prepare_input_only=prepare_input_only,
        )
        jobs.append(j)
        outs.append(j.output["tdolap_path"])

    # collect canac ouputs
    last_batch_job = jobs[-1]
    j = qdyn_cat_canac_outputs(
        tdolap_paths=outs,
        md_dt=prenamd_input.md_dt,
        surface_hopping=prenamd_input.surface_hopping,
        VBM=last_batch_job.output["VBM"],
        CBM=last_batch_job.output["CBM"],
        nproc=max(1, total_cpus // omp_python),
        plot=plot,
    )
    jobs.append(j)

    return jobs


@job
def qdyn_fused_scf_prenamd_task(
    software: str,
    scf_input: SCFInputT,
    prenamd_input: PreNAMDInputT,
    pp_path: str,
    orb_path: str,
    traj_file_path: str,
    traj_format: str,
    frame_start: int,
    frame_end: int,
    total_cpus: int,
    omp_software: int = 1,
    omp_python: int = 4,
    prepare_input_only: bool = False,
) -> dict:

    all_strus = read_strus(traj_format, traj_file_path=traj_file_path)
    software_lower = software.lower()
    nprocs = total_cpus // omp_python
    scf_step = scf_input.scf_step
    if scf_step < 0:
        scf_step = len(all_strus)

    selected_structures = all_strus[-scf_step:]
    batch_structures = selected_structures[frame_start:frame_end]
    n_frames = len(batch_structures)

    # Prepare common input files once (these will be copied to each subdir)
    inputs_dict = _prepare_scf_input(software_lower, scf_input)
    dftinputs = DFTInputs(
        software=software_lower,
        structure=batch_structures[0],
        pp_path=pp_path,
        orb_path=orb_path,
        kspacing=scf_input.kspacing,
        inputs_dict=inputs_dict,
        inputs_params=scf_input.parameters,
    )
    dftinputs.write()
    

    if prepare_input_only:
        return {
            'run_dir': str(Path.cwd()),
            'successful': 0,
            'failed': [],
        }

    task_dir = Path.cwd()
    subdirs: list[str] = []
    numdigit = len(str(scf_step))

    for global_idx, structure in zip(range(frame_start, frame_end), batch_structures):
        subdir_name = f"scf_{global_idx + 1:0{numdigit}d}" # 1-based index
        subdir_path = task_dir / subdir_name

        # Create subdirectories and write structure
        subdir_path.mkdir(exist_ok=True)
        write_stru(software_lower, structure, subdir_path)

        subdirs.append(str(subdir_path))

    successful = 0
    failed = []
    prev_chgcar = None
    chgcar = chg_name[software_lower]
    files_to_copy = ipt_files[software_lower]
    vbm, cbm = 0, 0

    # Run SCF calculations sequentially with CHGCAR passing
    is_first_step = True
    for idx_start in range(0, n_frames, nprocs):
        # scf block
        for subdir in subdirs[idx_start : idx_start + nprocs]:
            
            # Prepare this subdirectory - link input files from task_dir
            for fname in files_to_copy:
                os.symlink(fname, os.path.join(subdir, fname))

            # Move CHGCAR from previous successful calculation for faster convergence
            if prev_chgcar is not None:
                shutil.move(prev_chgcar, os.path.join(subdir, chgcar))

            # Mark as running
            _set_status(subdir, STATUS_RUNNING)

            # Change to subdirectory and run
            os.chdir(subdir)

            try:
                # Run VASP
                run_software(
                    software=software_lower, 
                    nprocs=total_cpus // omp_software, 
                    is_alle=scf_input.is_alle,
                    omp=omp_software
                )

                # Validate output
                _validate_scf_output(software_lower)

                # Mark as ended
                _set_status(subdir, STATUS_ENDED)
                successful += 1

                # Update prev_chgcar for next iteration
                prev_chgcar = os.path.join(subdir, chgcar)

            except Exception as e:
                # Mark as failed
                failed_idx = subdir.split('_')[-1] # 1-based
                raise RuntimeError(
                    f"SCF calculation failed for frame {failed_idx}"
                ) from e

            finally:
                os.chdir(task_dir)

        # prenamd block
        if is_first_step:
            vbm, cbm, nbands = extract_band_edges(
                software_lower, 
                subdirs[0],
                prenamd_input.adv.ikpt,
                prenamd_input.adv.ispin,
            )
            bmin = parse_band_index(prenamd_input.bmin, vbm, nbands)
            bmax = parse_band_index(prenamd_input.bmax, vbm, nbands)
            canac: Generator[dict[str, Any] | None, None, None] = extract_tdolaps(
                run_dirs=subdirs,
                software=software_lower,  # type: ignore
                is_gamma_ver=dftinputs.gamma,
                is_alle=prenamd_input.adv.alle,
                bmin=bmin,
                bmax=bmax,
                ikpt=prenamd_input.adv.ikpt,
                ispin=prenamd_input.adv.ispin,
                nproc=nprocs,
                dirs_sorted=True,
                generator=True,
            )
            is_first_step = False
        next(canac, None)

        # remove large out files
        idx_l = max(0, idx_start - 1)
        idx_r = idx_start + nprocs - 1
        for subdir in subdirs[idx_l:idx_r]:
            for fname in ['WAVECAR', 'CHG', 'CHGCAR']:
                fpath = os.path.join(subdir, fname)
                if os.path.isfile(fpath):
                    os.remove(fpath)

    # tdolap output
    out = next(canac, None)
    if out is None:
        raise RuntimeError("CA-NAC extraction did not produce a tdolap output.")
    # Ensure generator is exhausted
    next(canac, None)

    return {
        "run_dir": str(Path.cwd()),
        "software": software_lower,
        "VBM": vbm,
        "CBM": cbm,
        "tdolap_path": out['tdolap_path'],
    }

@job
def qdyn_cat_canac_outputs(
    tdolap_paths: list[str],
    md_dt: float,
    surface_hopping: str,
    VBM: int,
    CBM: int,
    nproc: int = 1,
    plot: bool = False,
):
    # readout tdolap_path
    check_list = []
    tdolaps = []
    eigenvalues = []
    for store_path in tdolap_paths:
        data = np.load(store_path)
        check_list.append(data["success"])
        tdolaps.append(data["tdolaps"])
        eigenvalues.append(data["eigenvalues"])

    check_list = np.concatenate(check_list, axis=0)
    tdolaps = np.concatenate(tdolaps, axis=0)
    eigenvalues = np.concatenate(eigenvalues, axis=0)
    data = {
        "success": check_list, 
        "eigenvalues": eigenvalues, 
        "tdolaps": tdolaps,
    }

    if not np.all(check_list):
        raise RuntimeError("Some steps failed in CA-NAC extraction. "
                           "Please check individual tdolap files for details.")

    nstep = len(check_list)
    tdolap_path = re.sub(r"nstep=\d+", f"nstep={nstep}", tdolap_paths[0])

    out = extract_nacs(
        data=data,
        tdolap_path=tdolap_path,
        nproc=nproc,
    )

    images = []
    if surface_hopping == 'DISH':
        output = calculate_dephasing_time(
            energies=out["eigenvalues"],
            md_dt=md_dt,
            plot=plot,
        )
        images.extend(output.get('images', []))

    return {
        "run_dir": str(Path.cwd()),
        "images": images[:10], # Only return the first 10 images to avoid overflow
        "VBM": VBM,
        "CBM": CBM,
        "nac_path": out['nac_path'],
        'deph_path': (
            str(Path.cwd() / 'DEPHTIME')
            if surface_hopping == 'DISH'
            else None
        ),
    }


