import os
import shutil
import logging
from pathlib import Path
from typing import Literal
from copy import deepcopy

import numpy as np

from ase import Atoms
from jobflow.core.job import job

from ..calc_common import read_stru, write_stru, stru_todict, xc_mapping, select_orbitals
from ..input import NVTInputT, DFTBaseInputT
from ..params import (
    PARAMS_DEFAULT, BAK_FNAMES,
    STRU_FNAME_MAPPING, STRU2_FNAME_MAPPING, 
    STRU_FORMAT_MAPPING, STRU2_FORMAT_MAPPING,
    ORBITAL_BASIS,
)
from ..input_prepare import DFTInputs
from ..output_postprocess import parse_md_data_from_qdyn_log, plot_md_results
from .run_software import run_software, MDProgressMonitor
from .seldyn import add_constraints


@job
def qdyn_nvt(
    software: str,
    parameters: NVTInputT,
    pp_path: str,
    orb_path: str,
    structure: dict,
    model_path: str = '',
    nodes: int = 1,
    processes_per_node: int = 1,
    threads_per_process: int = 1,
    plot: bool = False,
    prepare_input_only: bool = False,
) -> dict:
    """Run NVT molecular dynamics simulation with automatic retry on temperature divergence.

    Jobflow automatically manages the working directory, so all input files
    are written to the current directory.

    If temperature does not converge within 10% of target temperature, the
    simulation will be restarted using CONTCAR as the new structure, up to
    MAX_NVT_RETRIES times.

    Args:
        software: Software name ('vasp', 'cp2k', etc.).
        parameters: NVT simulation parameters.
        pp_path: Path to pseudopotential files.
        orb_path: Path to orbital files (for SIESTA/ABACUS/OpenMX).
        structure: Atomic structure.
        model_path: Path to the model file.
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
        - contcar: Final atomic structure (from CONTCAR)

    Raises:
        RuntimeError: If SCF convergence fails or temperature does not
            converge after MAX_NVT_RETRIES attempts.
    """

    software_lower = software.lower()

    # select orbitals
    if software_lower == 'openmx':
        ORBITAL_BASIS.clear()
        ORBITAL_BASIS.update(select_orbitals(software_lower, 'Quick'))

    structure.pop('momenta', None)
    cur_stru = Atoms.fromdict(structure)
    if (
        parameters.sel.constraint_layers is not None
        and not cur_stru.constraints
    ):
        cur_stru = add_constraints(cur_stru, parameters.sel)

    nprocs = nodes * processes_per_node
    images = []
    md_logs = []

    thermostats_algos = parameters.thermostats_algo
    md_steps = parameters.md_step
    temp_beg = parameters.temp_begin
    temp_end = parameters.temp_end
    calculator = parameters.calculator
    check_convergence = False
    nrounds = len(md_steps)
    
    for idx, (algo, md_step) in enumerate(zip(thermostats_algos, md_steps)):
        attempt = idx + 1

        if isinstance(calculator, DFTBaseInputT):
            # Prepare input files
            dftinputs = _prepare_nvt_input(
                software=software_lower,
                structure=cur_stru, # type: ignore
                parameters=parameters,
                pp_path=pp_path,
                orb_path=orb_path,
                thermostats=algo,
                md_step=md_step,
                temp_beg=temp_beg,
                temp_end=temp_end,
            )

            if prepare_input_only:
                return {
                    'run_dir': str(Path.cwd()),
                    'software': software,
                }

            # Run the software with progress monitoring
            with MDProgressMonitor(
                software=software_lower, # type: ignore
                nstep=md_step,
                scf_thr=calculator.scf_thr,
                md_dt=parameters.md_dt,
                log_every=parameters.log_every,
                check_convergence=check_convergence
            ) as m:
                run_software(software_lower, nprocs, monitor=m, cell=cur_stru.get_cell())
            # update structure
            cur_stru = read_stru(STRU2_FORMAT_MAPPING[software_lower],
                                 STRU2_FNAME_MAPPING[software_lower])
        else:
            write_stru(STRU_FNAME_MAPPING[software_lower],
                       cur_stru,
                       stru_format=STRU_FORMAT_MAPPING[software_lower],
                       extras=None)
            if prepare_input_only:
                return {
                    'run_dir': str(Path.cwd()),
                    'software': software,
                }
            scf_converged, cur_stru = _run_ase_nvt(
                cur_stru, # type: ignore
                parameters, 
                model_path,
                thermostats=algo,
                md_step=md_step,
                temp_beg=temp_beg,
                temp_end=temp_end,
            )
            write_stru(STRU2_FNAME_MAPPING[software_lower],
                       cur_stru,
                       stru_format=STRU2_FORMAT_MAPPING[software_lower],
                       extras=None)
            if check_convergence and not scf_converged:
                raise RuntimeError("NVT calculation failed: "
                                   "SCF did not converge in ASE MD run.")

        # Process output and update current structure
        backup_dir = Path(f"nvt_attempt_{attempt}").resolve()
        md_data = parse_md_data_from_qdyn_log('qdyn_md.log')
        md_logs.append(str(backup_dir / 'qdyn_md.log'))
        if plot:
            plot_md_results(md_data, 'qdyn_nvt.png', target_temp=temp_end)
            images.append(str(backup_dir / 'qdyn_nvt.png'))

        # check convergence
        converged = False
        if check_convergence or nrounds == 1:
            converged, temp_avg, temp_std = check_nvt_convergence(
                cur_stru, # type: ignore
                md_data,
                target_temp=temp_end,
            )

        # finish condition
        if converged:
            break
        else:
            # Backup current round files
            backup_dir.mkdir(exist_ok=True)

            backups = BAK_FNAMES[software_lower].copy()
            backups.extend(['qdyn_md.log', 'qdyn_nvt.png'])

            for f in backups:
                if os.path.isfile(f):
                    shutil.move(f, backup_dir / f)
                else:
                    logging.warning(f'File {f} not found, '
                                    'backup files may be incomplete.')
        # updates
        temp_beg = temp_end
        check_convergence = True

    else:
        error_msg = (
            f"NVT calculation failed: Did not converge after {nrounds} attempts. "
            f"Please check the system or increase the number of NVT rounds."
        )
        raise RuntimeError(error_msg)
    
    if md_logs:
        md_logs[-1] = str(Path.cwd() / 'qdyn_md.log')
    if images:
        images[-1] = str(Path.cwd() / 'qdyn_nvt.png')

    stru_dict = stru_todict(cur_stru)
    return {
        'run_dir': str(Path.cwd()),
        'software': software,
        'md_logs': md_logs,
        'images': images,
        'stru': stru_dict,
    }


def _prepare_nvt_input(
    software: str,
    structure: Atoms,
    parameters: NVTInputT,
    pp_path: str,
    orb_path: str,
    thermostats: str,
    md_step: int,
    temp_beg: float,
    temp_end: float,
):
    """Prepare input files for NVT molecular dynamics.

    This function prepares input files (POSCAR, KPOINTS, POTCAR, INCAR for VASP)
    for an NVT molecular dynamics calculation in the current directory.

    Args:
        software: Software name ('vasp', etc.).
        structure: Atomic structure.
        parameters: NVT parameters including kspacing, encut, temperature
            range, etc.
        pp_path: Path to pseudopotential directory.
        orb_path: Path to orbital files (for SIESTA/ABACUS/OpenMX).
        thermostats: Thermostat algorithm to use ('bussi', 'rescale_v', 'nhc').
        md_step: Number of MD steps to run.
        temp_beg: Initial temperature for the NVT simulation.
        temp_end: Final temperature for the NVT simulation.
    """
    assert isinstance(parameters.calculator, DFTBaseInputT)

    input = deepcopy(PARAMS_DEFAULT['nvt'][software])
    if software == 'vasp':
        input = xc_mapping(software, parameters.calculator.xc, input)
        # Handle predefined parameters in InputT
        if thermostats == 'nhc':
            input['MDALGO'] = 4
            input['NHC_NCHAINS'] = parameters.md_thermostats.nhc_tchain
            input['NHC_PERIOD'] = parameters.md_thermostats.nhc_tdamp // parameters.md_dt
            # input['ISIF'] = 0
        elif thermostats == 'rescale_v':
            # input['MDALGO'] = 0
            # input['ISIF'] = 0
            input['SMASS'] = -1
            input['NBLOCK'] = parameters.md_thermostats.rescale_v_nraise
        else:
            raise NotImplementedError()
        input['POTIM'] = parameters.md_dt
        input['NSW'] = md_step
        input['TEBEG'] = temp_beg
        input['TEEND'] = temp_end
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
    elif software == 'openmx':
        input = xc_mapping(software, parameters.calculator.xc, input)
        input['md.timestep'] = parameters.md_dt
        input['md.maxiter'] = md_step
        input['scf.criterion'] = parameters.calculator.scf_thr
        if thermostats == 'nhc':
            input['md.type'] = 'NVT_NH' # openmx only has nh
            input['nh.mass.heatbath'] = (2.97e-6*structure.get_number_of_degrees_of_freedom()
                *((temp_beg + temp_end)/2)*parameters.md_thermostats.nhc_tdamp**2) 
            # mass Q = g*k_B*T*tdamp^2 , unit: amu*bohr^2, g is dof, tdamp's unit is fs here
            input['md.tempcontrol'] = ['2', f'{1:<5} {temp_beg}', f'{md_step:<5} {temp_end}']
        elif thermostats == 'rescale_v':
            input['md.type'] = 'NVT_VS'
            input['md.tempcontrol'] = [
                '2', 
                f'{1:<5} {parameters.md_thermostats.rescale_v_nraise} {temp_beg} 0.0', 
                f'{md_step:<5} {parameters.md_thermostats.rescale_v_nraise} {temp_end} 0.0'
            ]
        else:
            raise NotImplementedError()
        dftinputs = DFTInputs(
            software='openmx',
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
            f"Software {software} is not supported for NVT input preparation yet."
        )
    return dftinputs


def check_nvt_convergence(
    structure: Atoms,
    md_data: dict,
    target_temp: float,
    last_nsteps: int | None = None,
    thres_avg: float = 0.004,
    thres_std: float = 1.1,
    thres_potential_slope: float = 0.01,
    thres_potential_drift: float = 0.005, # very loose threshold
) -> tuple[bool, float, float]:
    """Check NVT convergence from MD data (universal for all software).

    This function checks if temperature converged to the target value and
    potential energy reached a plateau.

    Args:
        md_data: MD data dictionary with 'temperatures' field.
        target_temp: Target temperature for NVT simulation.
        thres_avg: Maximum allowed average deviation.
        thres_std: Maximum allowed standard deviation.
        thres_potential_slope: Maximum allowed potential energy slope in eV/atom/ps.
        thres_potential_drift: Maximum allowed difference between first-half
            and second-half mean potential energy in eV/atom.

    Returns:
        tuple:
        - converged: True if temperature and potential energy converged
        - temp_avg: Average temperature of last n_last steps
        - temp_std: Standard deviation of temperature of last n_last steps
    """
    temps = np.asarray(md_data['temperatures'], dtype=float)
    potential_energies = np.asarray(
        md_data['potential_energies'],
        dtype=float,
    )
    if len(potential_energies) != len(temps):
        raise ValueError("Temperature and potential energy data lengths differ; "
                        "cannot check NVT convergence.")
    time_ps = np.asarray(md_data['time_ps'], dtype=float)
    if len(time_ps) != len(temps):
        raise ValueError("Temperature and time_ps data lengths differ; "
                        "cannot check NVT convergence.")

    if last_nsteps is not None:
        temps = temps[-last_nsteps:]
        potential_energies = potential_energies[-last_nsteps:]
        time_ps = time_ps[-last_nsteps:]

    if len(temps) == 0:
        raise ValueError("No temperature data available to check convergence.")

    temp_avg = temps.mean()
    temp_std = temps.std()

    target_avg = target_temp
    dof = structure.get_number_of_degrees_of_freedom()
    target_std = np.sqrt(2 / dof) * target_avg

    converged = True
    if abs(temp_avg - target_avg) > thres_avg * target_avg:
        converged = False
    if temp_std > thres_std * target_std:
        converged = False

    natoms = len(structure)
    potential_per_atom = potential_energies / natoms
    
    energy_slope = np.polyfit(time_ps - time_ps[0], potential_per_atom, 1)[0]
    if abs(energy_slope) > thres_potential_slope:
        converged = False
    
    half_index = len(potential_per_atom) // 2
    first_half_mean = potential_per_atom[:half_index].mean()
    second_half_mean = potential_per_atom[half_index:].mean()
    potential_drift = second_half_mean - first_half_mean
    if abs(potential_drift) > thres_potential_drift:
        converged = False

    return converged, temp_avg, temp_std


def _run_ase_nvt(
    structure: Atoms, 
    parameters: NVTInputT, 
    model_path: str,
    thermostats: str,
    md_step: int,
    temp_beg: float,
    temp_end: float,
):
    """Run NVT MD using ASE's integrator.

    Args:
        structure: Initial atomic structure with positions and momenta (optional).
        parameters: NVT simulation parameters.
        model_path: Path to the machine learning model.
        thermostats: Thermostat algorithm to use ('bussi', 'rescale_v', 'nhc').
        md_step: Number of MD steps to run.
        temp_beg: Initial temperature for the NVT simulation.
        temp_end: Final temperature for the NVT simulation.

    Returns:
        tuple: (scf_converged, final_structure)
    """
    import ase.units
    from ase.md import MDLogger
    from ..input import NequipInputT, MACEInputT
    from ..calc_common import TrajWriter
    from ..ml_tools.mlff_wrapper import get_mlff_calculator

    md_dt = parameters.md_dt
    log_every = parameters.log_every
    accelerator = parameters.calculator
    heatbath = parameters.md_thermostats

    # check gpu availability
    assert isinstance(accelerator, (NequipInputT, MACEInputT))
    if accelerator and accelerator.use_gpu:
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("GPU acceleration requested but no CUDA device found.")
        
    # initial velocities
    if np.allclose(structure.get_velocities(), 0.0):
        try:
            # ase >= 3.29.0
            from ase.md.velocitydistribution import thermalize_momenta as MaxwellBoltzmannDistribution # type: ignore
        except ImportError:
            from ase.md.velocitydistribution import MaxwellBoltzmannDistribution

        MaxwellBoltzmannDistribution(structure, temperature_K=temp_beg)

    # set up dyn and thermostat
    if thermostats == 'bussi':
        from ase.md.bussi import Bussi
        dyn = Bussi(structure, 
                    timestep=md_dt * ase.units.fs,
                    temperature_K=temp_beg,
                    taut=heatbath.bussi_taut * ase.units.fs)
        
        def bussi_ramp_temperature():
            step = dyn.get_number_of_steps()
            
            fraction = step / md_step
            temp_target = temp_beg + fraction * (temp_end - temp_beg)

            # update target temperature
            dyn.temp = temp_target * ase.units.kB
            dyn.target_kinetic_energy = 0.5 * dyn.temp * dyn.ndof

        if temp_beg != temp_end:
            dyn.attach(bussi_ramp_temperature, interval=1)

    elif thermostats == 'rescale_v':
        from ase.md.verlet import VelocityVerlet
        dyn = VelocityVerlet(structure,
                             timestep=md_dt * ase.units.fs)
        
        def rescale_v_ramp_velocities():
            step = dyn.get_number_of_steps()

            fraction = step / md_step
            temp_target = temp_beg + fraction * (temp_end - temp_beg)
            temp_now = dyn.atoms.get_temperature()

            alpha = np.sqrt(temp_target / temp_now)
            cur_vel = dyn.atoms.get_velocities()
            dyn.atoms.set_velocities(alpha * cur_vel)

        dyn.attach(rescale_v_ramp_velocities, interval=heatbath.rescale_v_nraise)

    elif thermostats == 'nhc':
        from ase.md.nose_hoover_chain import NoseHooverChainNVT
        if temp_beg != temp_end:
            raise NotImplementedError(
                "Temperature ramping is not implemented "
                "for Nose-Hoover Chain thermostat yet."
            )
        dyn = NoseHooverChainNVT(structure,
                                 timestep=md_dt * ase.units.fs,
                                 temperature_K=temp_beg,
                                 tdamp=heatbath.nhc_tdamp * ase.units.fs,
                                 tchain=heatbath.nhc_tchain)
        
    else:
        raise NotImplementedError(
            "Selected thermostat is not implemented yet.\n"
            "Supported: 'bussi', 'rescale_v', 'nhc'."
        )

    # logging
    logfile = open('qdyn_md.log', 'w')
    logfile.write(f'Step: {md_step}, Interval: {log_every}\n')
    md_logger = MDLogger(dyn, structure, logfile, mode='w')
    dyn.attach(md_logger, interval=log_every)

    traj_writer = TrajWriter(dyn, structure)
    dyn.attach(traj_writer, interval=log_every)

    calculator = get_mlff_calculator(
        accelerator, 
        model_path, 
        dispersion=accelerator.dispersion
    )
    structure.set_calculator(calculator)

    # md run
    converged = dyn.run(md_step)

    # cleanup
    logfile.close()
    traj_writer.close()

    return converged, structure
