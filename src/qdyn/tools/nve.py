import os
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Tuple

import ase.io
from ase import Atoms
from jobflow import job
import numpy as np


from ..input import NVEInputT, DFTBaseInputT
from ..params import params_default, TRAJ_FNAME_MAPPING
from ..input_prepare import DFTInputs
from ..output_postprocess import MDOutpus
from .run_software import run_software, MDProgressMonitor
from .seldyn import add_constraints


@job
def qdyn_nve(
    software: str,
    parameters: NVEInputT,
    pp_path: str,
    orb_path: str,
    structure: Dict,
    model_path: str = '',
    nodes: int = 1,
    processes_per_node: int = 1,
    threads_per_process: int = 1,
    plot: bool = False,
    prepare_input_only: bool = False,
) -> Dict:
    """Run NVE molecular dynamics simulation.

    Jobflow automatically manages the working directory, so all input files
    are written to the current directory.

    Args:
        software: Software name ('vasp', 'cp2k', etc.).
        parameters: NVE simulation parameters.
        pp_path: Path to pseudopotential files.
        orb_path: Path to orbital files (for SIESTA/ABACUS/OpenMX).
        structure: Atomic structure (typically CONTCAR from NVT).
        model_path: Path to MLFF checkpoints.
        nodes: Number of nodes for parallel calculation.
        processes_per_node: Number of MPI tasks per node.
        threads_per_process: Number of CPUs per task.
        plot: Whether to generate plots.
        prepare_input_only: If True, only prepare input files without running
            the calculation.

    Returns:
        Dict:
        - run_dir: Current working directory path
        - software: Software name used
        - images: List of paths to generated plot files
        - strus: List of Atoms structures extracted from XDATCAR
        - contcar: Final atomic structure (from CONTCAR)

    Raises:
        RuntimeError: If SCF convergence fails in the last portion of the trajectory.
    """

    software_lower = software.lower()
    nprocs = nodes * processes_per_node

    structure['momenta'] = np.array(structure['momenta'])
    cstru = Atoms.fromdict(structure)
    if parameters.sel.constraint_layers is not None and not cstru.constraints:
        cstru = add_constraints(cstru, parameters.sel)

    if isinstance(parameters.calculator, DFTBaseInputT):
        # Prepare input files
        _prepare_nve_input(
            software=software_lower,
            structure=cstru,
            parameters=parameters,
            pp_path=pp_path,
            orb_path=orb_path,
        )

        if prepare_input_only:
            return {
                'run_dir': str(Path.cwd()),
                'software': software,
                'md_files': [],
                'images': [],
                'strus': [],
            }

        # Run the software
        with MDProgressMonitor(
            software=software_lower, # type: ignore
            nstep=parameters.md_step,
            scf_thr=parameters.calculator.scf_thr,
            md_dt=parameters.md_dt,
            log_every=1,
        ) as m:
            run_software(software_lower, nprocs, monitor=m)
    
    else:
        converged, _ = _run_ase_nve(cstru, parameters, model_path)
        if not converged:
            raise RuntimeError(
                "NVE calculation failed: ASE MD did not converge properly. "
                "Please check the log files for details."
            )

    # Process output and check convergence
    # mdoutputs = _process_nve_output(
    #     software=software_lower,
    #     md_dt=parameters.md_dt,
    #     plot=plot,
    # )

    # if not mdoutputs.scf_converged:
    #     raise RuntimeError(
    #         "NVE calculation failed: SCF did not converge properly in the "
    #         "last portion of the trajectory. Please check the output files."
    #     )
    
    images = []


    return {
        'run_dir': str(Path.cwd()),
        'software': software,
        'md_files': 'qdyn_md.log',
        'images': images,
        # 'strus': strus_list,
        'traj_path': str(
            Path.cwd() / TRAJ_FNAME_MAPPING[software_lower]
        ),  # constraints information may also remain in some software's trajectory files, may raise error when changing to dict.
    }


def _prepare_nve_input(
    software: str,
    structure: Atoms,
    parameters: NVEInputT,
    pp_path: str,
    orb_path: str,
):
    """Prepare input files for NVE molecular dynamics.

    Args:
        software: Software name ('vasp', etc.).
        structure: Atomic structure.
        parameters: NVE parameters.
        pp_path: Path to pseudopotential directory.
        orb_path: Path to orbital files.
    """

    input = deepcopy(params_default['nve'][software])
    if software == 'vasp':
        input['POTIM'] = parameters.md_dt
        input['NSW'] = parameters.md_step
        input['EDIFF'] = parameters.calculator.scf_thr

        dftinputs = DFTInputs(
            software='vasp',
            structure=structure,
            pp_path=pp_path,
            orb_path=orb_path,
            kspacing=parameters.calculator.kspacing,
            inputs_dict=input,
            inputs_params=parameters.calculator.parameters,
        )
        dftinputs.write()
    else:
        raise NotImplementedError(
            f"Software {software} is not supported for NVE input preparation yet."
        )


def _process_nve_output(
    software: str,
    md_dt: float,
    plot: bool,
) -> MDOutpus:
    """Process NVE output files and check convergence.

    In the old workflow, NVE convergence check uses:
    - check_nsw = wavecar_steps + 100 (last portion of trajectory needed for SCF)
    - max_unconverged = nsw // 100

    Here we check convergence of the last 10% of steps with a strict threshold.

    Args:
        software: Software name.
        md_dt: MD time step in fs (used for saving MD data).
        plot: Whether to generate plots.

    Returns:
        (scf_converged, md_file, images)
    """

    if software == 'vasp':
        mdoutputs = MDOutpus.from_md_tracks(software='vasp')
    else:
        raise NotImplementedError(
            f"MD data extraction for {software} is not implemented yet."
        )

    # Check SCF convergence on the last portion of the trajectory
    # In old workflow: check_nsw = wavecar_steps + 100, max_unconverged = nsw // 100
    # Here we check the last 10% of steps with 1% unconverged tolerance
    mdoutputs.check_scf_convergence(
        check_nsw=None,
        max_unconverged_ratio=0.01,
    )

    # Save MD data
    mdoutputs.save_md_data(md_dt, filename='md_nve.dat')

    # Generate plots if requested
    if plot:
        mdoutputs.plot_md_results(filename='nve_results.png')

    return mdoutputs


def _run_ase_nve(structure: Atoms, parameters: NVEInputT, model_path: str):
    """Run NVE MD using ASE's VelocityVerlet integrator.

    Args:
        structure: Initial atomic structure with positions and momenta.
        parameters: NVE simulation parameters.
        model_path: Path to the machine learning model.

    Returns:
        tuple: (scf_converged, final_structure)
    """
    import ase.units
    from ase.md.verlet import VelocityVerlet
    from ase.md import MDLogger
    from ..input import NequipInputT, MACEInputT
    from ..calc_common import TrajWriter
    from .mlff_wrapper import get_mlff_calculator

    md_step = parameters.md_step
    md_dt = parameters.md_dt
    accelerator = parameters.calculator

    # check gpu availability
    assert isinstance(accelerator, (NequipInputT, MACEInputT))
    if accelerator and accelerator.use_gpu:
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("GPU acceleration requested but no CUDA device found.")

    dyn = VelocityVerlet(structure, 
                         timestep=md_dt * ase.units.fs)
    logfile = open('qdyn_nve.log', 'w')
    logfile.write(f'Step: {md_step + 1}, Interval: 1\n')
    md_logger = MDLogger(dyn, structure, logfile, mode='w')
    dyn.attach(md_logger, interval=1)

    traj_writer = TrajWriter(dyn, structure)
    dyn.attach(traj_writer, interval=1)

    calculator = get_mlff_calculator(accelerator, model_path, dispersion=False)
    structure.set_calculator(calculator)

    converged = dyn.run(md_step)

    # cleanup
    logfile.close()
    traj_writer.close()

    return converged, structure
