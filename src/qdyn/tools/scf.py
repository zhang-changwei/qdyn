"""
SCF (Self-Consistent Field) calculation module for NAMD workflow.

This module handles static SCF calculations on structures extracted from NVE
trajectory. It supports:
- Batch processing with configurable batch size
- Sequential CHGCAR passing between frames for faster convergence
- Status file tracking (RUNNING, ENDED, FAIL) for resume capability
"""

import os
import re
import shutil
from copy import deepcopy
from pathlib import Path

from ase import Atoms
from jobflow.core.job import job, Job
import numpy as np
from pydantic import BaseModel

from ..calc_common import write_stru, read_strus, change_dir
from ..input import SCFInputT, DFTBaseInputT
from ..params import params_default, CHG_FNAME, INPUT_FNAMES, STRU_FNAME_MAPPING
from ..input_prepare import DFTInputs
from ..output_postprocess import read_scfout, calc_openmx_HK_SK_gamma
from .run_software import run_software

class SCFLogger:

    def __init__(self, nstep: int, fname: str = 'qdyn_scf.log', retry: bool = False):
        if not retry:
            self.log_file = open(fname, 'w')
            self.log_file.write(
                f"Step: {nstep}, Interval: 1\n"
                f"Step     Global_idx     Category\n"
            )
            self.log_file.flush()
            self.cur_step = -1
        else:
            self.log_file = open(fname, 'r+')
            f = self.log_file
            f.readline()
            f.readline()
            line = ''
            for line in f.readlines():
                pass
            try:
                parts = line.split()
                self.cur_step = int(parts[0])
            except Exception:
                raise ValueError("Failed to parse last line of log file for retry")

    def __call__(self, step: int, global_idx: str, category: str):
        self.log_file.write(
            "{:<10d} {:12s} {:12s}\n".format(
                step, global_idx, category
            )
        )
        self.log_file.flush()

    def close(self):
        self.log_file.close()

class SCFSolverStub:

    def add(self, step: int, job_dir: Path, stru: Atoms):
        pass

    def close(self):
        pass

    def run(self):
        pass


class TrajInfo(BaseModel):
    path: str
    format: str
    start: int
    stop: int



def qdyn_scf(
    software: str,
    parameters: SCFInputT,
    pp_path: str,
    orb_path: str,
    traj_path: str,
    traj_format: str = 'vasp-xdatcar',
    model_path: str = '',
    nodes: int = 1,
    processes_per_node: int = 1,
    threads_per_process: int = 1,
    plot: bool = False,
    prepare_input_only: bool = False,
    retry: bool = False,
) -> list[Job]:
    """Create SCF jobs for frames from the NVE trajectory.

    This is a task distribution function (NOT @job decorated) that:
    1. Creates a Job for each batch based on batch_size and md_step

    Args:
        software: Software name ('vasp', etc.).
        parameters: SCF calculation parameters including scf_step, md_step,
            batch_size.
        pp_path: Path to pseudopotential files.
        orb_path: Path to orbital files.
        traj_path: Path to the trajectory file (e.g. XDATCAR for VASP).
        traj_format: Format of the trajectory file.
        model_path: Path to ML model (if using ML-based SCF solver).
        nodes: Number of nodes.
        processes_per_node: MPI tasks per node.
        threads_per_process: CPUs per task.
        plot: Whether to generate TDKS plot.
        prepare_input_only: If True, only prepare input files.
    Returns:
        List of SCF Job objects, one per batch.
    """

    batch_size = parameters.batch_size
    total_frames = parameters.scf_step
    has_tail = False

    jobs = []

    # Create a job for each batch
    for batch_idx in range(0, total_frames, batch_size):
        batch_end = min(batch_idx + batch_size + 1, total_frames)
        if batch_end == total_frames:
            has_tail = True

        # Global frame indices (0-based)
        frame_start = batch_idx
        frame_end = batch_end

        j = qdyn_scf_cpu(
            software=software,
            parameters=parameters,
            pp_path=pp_path,
            orb_path=orb_path,
            traj=TrajInfo(
                path=traj_path,
                format=traj_format,
                start=frame_start,
                stop=frame_end,
            ),
            model_path=model_path,
            nodes=nodes,
            processes_per_node=processes_per_node,
            threads_per_process=threads_per_process,
            prepare_input_only=prepare_input_only,
            has_tail=has_tail,
            retry=retry,
        )
        jobs.append(j)

    return jobs


@job
def qdyn_scf_cpu(
    software: str,
    parameters: SCFInputT,
    pp_path: str,
    orb_path: str,
    traj: TrajInfo,
    model_path: str = '',
    nodes: int = 1,
    processes_per_node: int = 1,
    threads_per_process: int = 1,
    prepare_input_only: bool = False,
    has_tail: bool = False,
    retry: bool = False,
) -> dict:
    """Run a batch of SCF calculations for multiple structures.

    This job:
    1. Reads structures from the trajectory file (e.g. XDATCAR)
    2. Creates subdirectories for each structure (scf_XXXX format)
    3. Prepares common input files (INCAR, KPOINTS, POTCAR)
    4. Runs SCF calculations sequentially with CHGCAR passing
    5. Manages status files for resume capability
    Args:
        software: Software name.
        parameters: SCF parameters.
        pp_path: Pseudopotential path.
        orb_path: Orbital file path.
        traj: Information about the trajectory file.
        nodes: Number of compute nodes.
        processes_per_node: MPI tasks per node.
        threads_per_process: CPUs per task.
        prepare_input_only: If True, only prepare input files without running.

    Returns:
        Dict:
        - run_dir: Working directory path for this task
        - frame_range: (start, end) tuple of frame indices (inclusive)
        - successful: Number of successful SCF calculations
        - failed: List of failed frame indices
        - vbm: VBM band index (from the last successful calculation)
        - cbm: CBM band index (from the last successful calculation)
    """
    software = software.lower()
    calc = parameters.calculator
    scf_step = parameters.scf_step
    frame_start = traj.start

    strus = read_strus(traj.format, traj.path)
    strus = strus[-scf_step:]
    strus = strus[traj.start:traj.stop]
    n_frames = len(strus)
    nstep = n_frames - 1 # nstep >= 0
    scf_end = nstep if not has_tail else n_frames

    # Prepare common input files once (these will be copied to each subdir)
    if isinstance(calc, DFTBaseInputT):
        software_dft = software
        inputs_dict = _prepare_scf_input(software_dft, parameters)
        dftinputs = DFTInputs(
            software=software_dft,
            structure=strus[0],
            pp_path=pp_path,
            orb_path=orb_path,
            kspacing=calc.kspacing,
            inputs_dict=inputs_dict,
            inputs_params=calc.parameters,
        )
        postprocess = False
        # resources
        nprocs = nodes * processes_per_node
        omp = threads_per_process
        # logger and solver
        scf_logger = SCFLogger(nstep=n_frames, retry=retry)
        last_step = scf_logger.cur_step
        scf_solver = SCFSolverStub()
    else:
        software_dft = calc.ham_type
        inputs_dict = _prepare_scf_input(software_dft, parameters)
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
        # resources
        nprocs = processes_per_node * threads_per_process # nodes = 1
        omp = 1
        # logger and solver
        from ..ml_tools.hamgnn_wrapper import MLSCFSolver
        scf_logger = SCFLogger(nstep=n_frames, retry=retry)
        last_step = scf_logger.cur_step
        scf_solver = MLSCFSolver(
            software=software_dft,
            mlh_input=calc,
            model_path=model_path,
            logger=scf_logger,
            nproc=processes_per_node,
            threads_per_proc=threads_per_process,
        )
    dftinputs.write(stru=False)

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

    # Run SCF calculations sequentially with CHGCAR passing
    for idx, stru in enumerate(strus[:scf_end]):
        if idx <= last_step:
            # Skip already completed steps
            # TODO: retry hasn't completed yet
            continue

        # Create subdir, copy input files and write structure file
        global_idx = frame_start + idx + 1
        subdir = task_dir / f"scf_{global_idx:0{numdigit}d}"
        if subdir.is_dir(): # optional
            shutil.rmtree(subdir)
        subdir.mkdir(exist_ok=True)
        for fname in files_to_copy:
            shutil.copy2(task_dir / fname, subdir / fname)
        write_stru(software_dft, stru, subdir, extras=dftinputs.stru_extras)

        # Copy CHGCAR from previous successful calculation for faster convergence
        if prev_chgcar and prev_chgcar.is_file():
            shutil.copy2(prev_chgcar, subdir / chgcar)

        # Change to subdirectory and run
        with change_dir(subdir):
            run_software(
                software=software_dft, 
                nprocs=nprocs, 
                is_alle=parameters.is_alle,
                postprocess=postprocess,
                omp=omp,
            )
            _validate_scf_output(software, software_dft)

        # run scf solver
        scf_solver.add(idx, subdir, stru)

        # Updates and logging
        prev_chgcar = subdir / chgcar
        scf_logger(step=idx, global_idx=subdir.name, category='normal')
    
    # run solver for tail frames
    scf_solver.run()
    scf_solver.close()


    # tdoverlap calculation
    if software_dft == 'openmx':
        dftinputs.update_inputs({'postprocess.output.level': 1})
        dftinputs.update_stru_extras()

    if software_dft in {'abacus', 'openmx'}:
        for idx in range(nstep):
            global_idx = frame_start + idx + 1
            subdir = task_dir / f"scf_{global_idx:0{numdigit}d}"

            olapdir = subdir / "overlap"
            olapdir.mkdir(exist_ok=True)

            atoms = strus[idx].copy()
            atoms.extend(strus[idx + 1])
            for fname in files_to_copy:
                shutil.copy2(subdir / fname, olapdir / fname)
            write_stru(software_dft, atoms, olapdir, extras=dftinputs.stru_extras)

            with change_dir(olapdir):
                run_software(
                    software=software_dft,
                    nprocs=nprocs,
                    postprocess=True,
                    omp=omp,
                )

            # save overlap matrix
            scfout_data = read_scfout(str(olapdir / "qdyn.scfout"))
            SK = calc_openmx_HK_SK_gamma(scfout_data, tdt=True)
            np.save(olapdir / "overlap.npy", SK)

            # logging
            scf_logger(step=idx, global_idx=subdir.name, category='overlap')
    
    scf_logger.close()

    return {
        'run_dir': str(task_dir),
        'software': software,
        'software_dft': software_dft,
    }


def _prepare_scf_input(
    software: str,
    parameters: SCFInputT,
) -> dict:
    """Prepare common input files (INCAR, KPOINTS, POTCAR) in current directory.

    These files will be copied to each subdirectory.

    Args:
        software: Software name ('vasp', etc.).
        parameters: SCF parameters.
    """
    input = {}
    if isinstance(parameters.calculator, DFTBaseInputT):
        input = deepcopy(params_default['scf'][software])
        if software == 'vasp':
            input['EDIFF'] = parameters.calculator.scf_thr
        elif software == 'openmx':
            input['scf.criterion'] = parameters.calculator.scf_thr * 1e-2 # unit: Hatree
        else:
            raise NotImplementedError(
                f"Software {software} is not supported for SCF input preparation yet."
            )
    else:
        input = deepcopy(params_default['scf'][software])
        if software == 'openmx':
            input['scf.energycutoff'] = parameters.calculator.ecut
        else:
            raise NotImplementedError(f"Software {software} is not supported for "
                                      "tdoverlap calculation input preparation yet.")

    return input


def _clean_all_files(subdir: str, stru: str):
    """Remove all status files from a subdirectory except the structure file.

    Args:
        subdir: Path to subdirectory.
        stru: Name of the structure file to preserve.
    """
    for fname in os.listdir(subdir):
        if fname == stru:
            continue
        fpath = os.path.join(subdir, fname)
        if os.path.isfile(fpath):
            os.remove(fpath)


def _validate_scf_output(software: str, software_dft: str):
    """Validate SCF calculation completed successfully.

    Checks for 'Total CPU' and SCF convergence in OUTCAR, reading only
    the file tail for efficiency.

    Raises:
        RuntimeError: If OUTCAR is missing or calculation did not
            complete/converge.
    """
    if software == 'vasp':
        if not os.path.isfile('OUTCAR'):
            raise RuntimeError("SCF calculation failed: OUTCAR not found.")

        with open('OUTCAR', 'rb') as f:
            content = f.read()

        # Check completion marker
        if b'Total CPU' not in content:
            raise RuntimeError(
                "SCF calculation failed: OUTCAR does not contain 'Total CPU' marker. "
                "The calculation may not have completed successfully."
            )

        # Check SCF convergence
        if b'aborting loop because EDIFF is reached' not in content:
            # Look for common convergence failure markers
            # if b'WARNING in EDDAV' in content or b'ZBRENT: fatal error' in content:
            #     raise RuntimeError(
            #         "SCF calculation failed: SCF did not converge. "
            #         "Check OUTCAR for convergence errors."
            #     )
            raise RuntimeError(
                "SCF calculation failed: SCF did not converge. "
                "OUTCAR does not contain 'aborting loop because EDIFF is reached' marker."
            )

        # Check WAVECAR file size
        if not os.path.isfile('WAVECAR'):
            raise RuntimeError("SCF calculation failed: WAVECAR not found.")
        if os.path.getsize('WAVECAR') == 0:
            raise RuntimeError(
                "SCF calculation failed: WAVECAR is empty. "
                "The calculation may not have completed successfully."
            )

        # Clean up unnecessary files
        for f in ['CHG', 'vasprun.xml']:
            if os.path.isfile(f):
                os.remove(f)
    elif software == 'openmx':
        if not os.path.isfile('qdyn.out'):
            raise RuntimeError("SCF calculation failed: qdyn.out not found.")
        
        with open('qdyn.out', 'r') as f:
            text = f.read()
            
        # Check completion marker
        if 'Elapsed.Time.' not in text:
            raise RuntimeError(
                "SCF calculation failed: qdyn.out does not contain 'Elapsed.Time.' marker. "
                "The calculation may not have completed successfully."
            )
            
        # Check SCF convergence
        max_iter_match = re.search(r"scf\.maxIter\s+([0-9]+)", text)
        if max_iter_match:
            try:
                scf_max_iter = int(max_iter_match.group(1))
            except ValueError:
                scf_max_iter = 40
        criterion_match = re.search(r"scf\.criterion\s+([0-9eE\.+\-]+)", text)
        if criterion_match:
            try:
                scf_criterion = float(criterion_match.group(1))
            except ValueError:
                scf_criterion = 1.0e-6

        scf_lines = re.findall(
            r"^\s*SCF=\s*([0-9]+)\s+NormRD=\s*([0-9eE\.+\-]+)\s+Uele=\s*([0-9eE\.+\-]+)",
            text,
            flags=re.MULTILINE,
        )

        last_step = int(scf_lines[-1][0])
        if last_step < scf_max_iter:
            return

        try:
            uele_last = float(scf_lines[-1][2])
            uele_prev = float(scf_lines[-2][2])
        except ValueError:
            raise RuntimeError(
                "SCF calculation failed: invalid Uele values in qdyn.out SCF history."
            )
        if abs(uele_last - uele_prev) >= scf_criterion:
            raise RuntimeError(
                "SCF calculation failed: SCF did not converge. "
                "qdyn.out last-step Uele change exceeds scf.criterion."
            )
            
    elif software == 'hamgnn':
        if software_dft == 'openmx':
            if not os.path.isfile('placeholder'):
                raise FileNotFoundError("Overlap matrix calculation failed: placeholder not found.")
        elif software_dft == 'abacus':
            if not os.path.isfile('placeholder'):
                raise FileNotFoundError("Overlap matrix calculation failed: placeholder not found.")
        else:
            raise NotImplementedError(
                f"Hamgnn does not support '{software_dft}' yet."
            )
    else:
        raise NotImplementedError(
            f"Validation for software '{software}' is not implemented."
        )
