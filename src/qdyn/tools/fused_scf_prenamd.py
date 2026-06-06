import os
import re
import shutil
from copy import deepcopy
from pathlib import Path
from collections.abc import Generator
from typing import Any, Sequence

import numpy as np
from jobflow.core.job import job, Job

from ..calc_common import (
    write_stru, read_strus, 
    parse_band_index, select_orbitals
)
from ..input import SCFInputT, PreNAMDInputT, DFTBaseInputT
from ..input_prepare import DFTInputs
from ..params import (
    CHG_FNAME, INPUT_FNAMES, 
    STRU_FNAME_MAPPING, STRU_FORMAT_MAPPING, 
    ORBITAL_BASIS
)
from ..output_postprocess import extract_band_edges
from .scf import TrajInfo, SCFLogger, DFTSCFSolver
from .scf import _prepare_scf_input, overlap_run_software
from .canac import extract_tdolaps, extract_nacs
from .dephase import calculate_dephasing_time

def qdyn_fused_scf_prenamd(
    software: str,
    scf_input: SCFInputT,
    prenamd_input: PreNAMDInputT,
    pp_path: str,
    orb_path: str,
    traj_path: str,
    traj_format: str,
    model_path: str,
    nodes: int = 1,
    ncpus: int = 1,
    nprocs_dft: int = 1,
    nprocs_py: int = 1,
    plot: bool = False,
    prepare_input_only: bool = False,
    retry: bool = False,
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

        if frame_end - frame_start <= 1:
            continue

        j = qdyn_fused_scf_prenamd_task(
            software=software,
            scf_input=scf_input,
            prenamd_input=prenamd_input,
            pp_path=pp_path,
            orb_path=orb_path,
            traj=TrajInfo(
                path=traj_path,
                format=traj_format,
                start=frame_start,
                stop=frame_end,
            ),
            model_path=model_path,
            ncpus=ncpus,
            nodes=nodes,
            nprocs_dft=nprocs_dft,
            nprocs_py=nprocs_py,
            prepare_input_only=prepare_input_only,
            retry=retry,
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
        nproc=nprocs_py,
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
    traj: TrajInfo,
    model_path: str,
    ncpus: int,
    nodes: int = 1,
    nprocs_dft: int = 1,
    nprocs_py: int = 1,
    prepare_input_only: bool = False,
    retry: bool = False,
) -> dict:

    software = software.lower()
    calc = scf_input.calculator
    omp_dft = max(1, ncpus // nprocs_dft)
    omp_py = max(1, ncpus // nprocs_py)
    nprocs_dft = max(1, ncpus // omp_dft) * nodes
    nprocs_py = max(1, ncpus // omp_py)
    scf_step = scf_input.scf_step

    strus = read_strus(traj.format, traj_path=traj.path)
    strus = strus[-scf_step:]
    strus = strus[traj.start:traj.stop]
    n_frames = len(strus)
    nstep = n_frames - 1

    # Prepare common input files once (these will be copied to each subdir)
    if isinstance(calc, DFTBaseInputT):
        software_dft = software
        # select orbitals
        if software_dft == 'openmx':
            ORBITAL_BASIS.clear()
            ORBITAL_BASIS.update(select_orbitals(software_dft, 'Standard'))
        
        inputs_dict = _prepare_scf_input(software_dft, scf_input)
        dftinputs = DFTInputs(
            software=software,
            structure=strus[0],
            pp_path=pp_path,
            orb_path=orb_path,
            kspacing=calc.kspacing,
            inputs_dict=inputs_dict,
            inputs_params=calc.parameters,
        )
        postprocess = False
        # logger and solver
        scf_logger = SCFLogger(nstep=n_frames, retry=retry)
        scf_solver = DFTSCFSolver(
            software=software_dft,
            scf_input=scf_input,
            inputs_dict=dftinputs.inputs,
            logger=scf_logger,
            nproc=nprocs_dft,
            threads_per_proc=omp_dft,
        )
        batch_size = nprocs_py
    else:
        software_dft = calc.ham_type
        # select orbitals
        if software_dft == 'openmx':
            ORBITAL_BASIS.clear()
            ORBITAL_BASIS.update(select_orbitals(software_dft, calc.nao_max))

        inputs_dict = _prepare_scf_input(software_dft, scf_input)
        if software_dft == 'openmx':
            inputs_dict['postprocess.output.level'] = (3 if calc.add_H0 else 1)
        elif software_dft == 'abacus':
            inputs_dict['calculation'] = 'get_s'
        dftinputs = DFTInputs(
            software=software_dft,
            structure=strus[0],
            pp_path=pp_path,
            orb_path=orb_path,
            kspacing=calc.kspacing,
            inputs_dict=inputs_dict,
        )
        postprocess = True
        # logger and solver
        from ..ml_tools.hamgnn_wrapper import MLSCFSolver
        scf_logger = SCFLogger(nstep=n_frames, retry=retry)
        scf_solver = MLSCFSolver(
            software=software_dft,
            mlh_input=calc,
            model_path=model_path,
            logger=scf_logger,
            nproc=nprocs_py,
            threads_per_proc=omp_py,
        )
        batch_size = calc.batch_size
    dftinputs.write(stru=False)

    # for overlap (use a copy to avoid mutating the SCF inputs_dict)
    if software_dft in ('abacus', 'openmx'):
        inputs_dict_olap = deepcopy(inputs_dict)
        if software_dft == 'openmx':
            inputs_dict_olap['postprocess.output.level'] = 1
        elif software_dft == 'abacus':
            inputs_dict_olap['calculation'] = 'get_s'
        dftinputs_olap = DFTInputs(
            software=software_dft,
            structure=strus[0],
            pp_path=pp_path,
            orb_path=orb_path,
            kspacing=calc.kspacing,
            inputs_dict=inputs_dict_olap,
        )
        import multiprocessing
        pool_olap = multiprocessing.Pool(processes=nprocs_py)

    if prepare_input_only:
        return {
            'run_dir': str(Path.cwd()),
            'software': software,
            'software_dft': software_dft,
        }

    # Task working directory
    task_dir = Path.cwd()
    numdigit = len(str(scf_step))

    prev_chgcar = None
    chgcar = CHG_FNAME[software_dft]
    files_to_copy = INPUT_FNAMES[software_dft].difference({STRU_FNAME_MAPPING[software_dft]})
    vbm, cbm = 0, 0

    # create subdirs list for canac
    subdirs: list[str] = []
    for global_idx in range(traj.start, traj.stop):
        subdir_name = f"scf_{global_idx + 1:0{numdigit}d}" # 1-based index
        subdir_path = task_dir / subdir_name
        subdirs.append(str(subdir_path))

    LARGE_FNAMES: dict[str, set] = {
        'vasp': {
            'WAVECAR', 'CHG', 'CHGCAR', 'OUTCAR', 
            'vasprun.xml', 'vaspout.h5'
        },
        'openmx': {
            'qdyn.scfout', 'qdyn.out'
        },
        'hamgnn': {
            'wfc.npz', 'overlap.npy', 'overlap.npz'
        }
    }
    def remove_large_outputs(
        softwares: Sequence[str],
        folders: Sequence[str | Path]
    ) -> None:
        fnames = set()
        for s in softwares:
            fnames = fnames.union(LARGE_FNAMES.get(s, set()))

        for folder in folders:
            for fname in fnames:
                fpath = os.path.join(folder, fname)
                if os.path.isfile(fpath):
                    os.remove(fpath)

    # Run SCF calculations sequentially with CHGCAR passing.
    # The outer loop iterates over CA-NAC pair groups: each group processes
    # pairs [canac_start, canac_end). Before running CA-NAC, SCF must complete
    # up to frame canac_end (inclusive) so that both endpoints of every pair
    # in the group have valid WAVECAR files.
    is_first_step = True
    out = None

    for canac_start in range(-batch_size, nstep, batch_size):
        canac_end = min(canac_start + batch_size, nstep)
        scf_start = 0 if is_first_step else canac_start + 1
        scf_end = 1 if is_first_step else canac_end + 1


        # scf block (head & normal frames)
        for scf_idx in range(scf_start, scf_end):
            stru = strus[scf_idx]

            # Create subdir, copy input files and write structure file
            subdir = Path(subdirs[scf_idx])
            if subdir.is_dir(): # optional
                shutil.rmtree(subdir)
            subdir.mkdir(exist_ok=True)
            for fname in files_to_copy:
                os.symlink(task_dir / fname, subdir / fname)
            write_stru(
                subdir / STRU_FNAME_MAPPING[software_dft], 
                stru,
                stru_format=STRU_FORMAT_MAPPING[software_dft],
                extras=dftinputs.stru_extras
            )

            # Move CHGCAR from previous successful calculation for faster convergence
            if prev_chgcar and prev_chgcar.is_file():
                shutil.move(prev_chgcar, subdir / chgcar)

            # run scf solver
            scf_solver.add(scf_idx, subdir, stru)

            # Update CHGCAR
            prev_chgcar = subdir / chgcar

        # ensure the solver is runned, normal frames auto satisfied
        # useful for head / tail frames
        scf_solver.run()


        # prenamd block (head frame)
        if is_first_step:
            vbm, cbm, nbands = extract_band_edges(
                software,
                subdirs[0],
                prenamd_input.adv.ikpt,
                prenamd_input.adv.ispin,
            )
            bmin = parse_band_index(prenamd_input.bmin, vbm, nbands)
            bmax = parse_band_index(prenamd_input.bmax, vbm, nbands)
            canac: Generator[dict[str, Any] | None, None, None] = extract_tdolaps(
                run_dirs=subdirs,
                software=software,  # type: ignore
                is_gamma_ver=dftinputs.gamma,
                is_alle=prenamd_input.adv.alle,
                bmin=bmin,
                bmax=bmax,
                ikpt=prenamd_input.adv.ikpt,
                ispin=prenamd_input.adv.ispin,
                nproc=nprocs_py,
                batch_size=batch_size,
                dirs_sorted=True,
                generator=True,
            )
            is_first_step = False
            continue


        # overlap block (normal frames)
        if software_dft in ('abacus', 'openmx'):
            results = []

            for canac_idx in range(canac_start, canac_end):
                subdir = Path(subdirs[canac_idx])

                olapdir = subdir / "overlap"
                olapdir.mkdir(exist_ok=True)

                atoms = strus[canac_idx].copy()
                atoms.extend(strus[canac_idx + 1])
                for fname in files_to_copy:
                    os.symlink(subdir / fname, olapdir / fname)
                write_stru(
                    olapdir / STRU_FNAME_MAPPING[software_dft],
                    atoms,
                    stru_format=STRU_FORMAT_MAPPING[software_dft],
                    extras=dftinputs_olap.stru_extras, # type: ignore
                )

                results.append(
                    pool_olap.apply_async( # pyright: ignore[reportPossiblyUnboundVariable]
                        overlap_run_software,
                        args=(subdir, olapdir, software_dft, omp_py)
                    )
                )

            # logging
            for canac_idx, result in zip(range(canac_start, canac_end), results):
                subdir = Path(subdirs[canac_idx])
                result.get()

                scf_logger(step=canac_idx, global_idx=subdir.name, category='overlap')
  

        # prenamd block (normal frames)
        next(canac, None) # type: ignore

        # Remove frames that cannot be needed by later CA-NAC pairs.
        # Keep frame canac_end — it is the left endpoint of the next group.
        remove_large_outputs((software, software_dft), subdirs[canac_start: canac_end])
        if software_dft in ('abacus', 'openmx'):
            remove_large_outputs(
                (software_dft),
                [os.path.join(f, 'overlap') 
                 for f in subdirs[canac_start: canac_end]]
            )


    # tdolap output
    out = next(canac, None) # type: ignore
    if out is None:
        raise RuntimeError("CA-NAC extraction did not produce a tdolap output.")
    # Ensure generator is exhausted before deleting the final boundary frame.
    next(canac, None) # type: ignore
    # last frame should not be cleaned

    # close the logger and solver
    scf_logger.close()
    scf_solver.close()
    if software_dft in ('abacus', 'openmx'):
        pool_olap.close() # pyright: ignore[reportPossiblyUnboundVariable]
        pool_olap.join() # pyright: ignore[reportPossiblyUnboundVariable]

    return {
        "run_dir": str(Path.cwd()),
        "software": software,
        "software_dft": software_dft,
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


