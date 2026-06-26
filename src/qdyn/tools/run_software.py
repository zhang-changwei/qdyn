from enum import Enum
import io
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Literal

import ase.units
from ..calc_common import read_stru, write_stru
from ..params import STRU2_FNAME_MAPPING, STRU2_FORMAT_MAPPING

_SRUN = (shutil.which("srun") is not None)
_INTEL_MPI_ENVS = {
    "I_MPI_PIN": "1",
    "I_MPI_PIN_DOMAIN": "core",
    "I_MPI_PIN_ORDER": "compact",
}

class DFTStatus(Enum):
    NORMAL = 0
    NOT_CONVERGED_ERROR = 1
    UNKNOWN_ERROR = 2

class MDProgressMonitor:

    MONITOR_FNAME_MAPPING = {
        'vasp': 'OSZICAR',
        'openmx': 'qdyn.ene',
    }

    def __init__(self, 
                 software: Literal['vasp', 'openmx'],
                 nstep: int, 
                 scf_thr: float = 1e-6,
                 md_dt: float = 1.0,
                 log_every: int = 1,
                 check_convergence: bool | str = True,
                 ):
        self.software = software
        self.nstep = nstep
        self.scf_thr = scf_thr
        self.log_every = log_every
        self.md_dt = md_dt
        self.check_convergence = check_convergence

        self.monitor_file = None
        self.log_file = None

        self.cur_time = self.md_dt * self.log_every * 1e-3
        self.prev_line = ""

    def __enter__(self):
        return self

    def __call__(self):
        if not self.monitor_file:
            m_fname = self.MONITOR_FNAME_MAPPING[self.software]
            if not os.path.isfile(m_fname):
                return
            self.monitor_file = open(m_fname, 'r')
        
        if not self.log_file:
            if self.check_convergence in (True, 'rigorous') and self.software == 'openmx':
                logging.warning("SCF convergence check disabled for OpenMX, "
                                    "please check SCF convergence manually.\n")
           
            self.log_file = open('qdyn_md.log', 'w')
            # Write header
            self.log_file.write(
                f"Step: {self.nstep}, Interval: {self.log_every}\n"
                f"Time[ps]       Etot[eV]     Epot[eV]     Ekin[eV]         T[K]\n"
            )
            self.log_file.flush()

        if self.software == 'vasp':
            status = self.monitor_vasp(self.monitor_file, self.log_file)
        elif self.software == 'openmx':
            status = self.monitor_openmx(self.monitor_file, self.log_file)
        else:
            raise NotImplementedError(
                f"Monitoring for software '{self.software}' is not implemented yet."
            )
        return status
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.monitor_file:
            self.monitor_file.close()
        if self.log_file:
            self.log_file.close()

    def monitor_vasp(self, monitor_file: io.TextIOWrapper, log_file: io.TextIOWrapper):
        '''VASP moves atoms first, so there is no output at step 0.'''
        while True:
            cur_pos = monitor_file.tell()
            line = monitor_file.readline()
            if not line:
                break
            if not line.endswith('\n'):
                monitor_file.seek(cur_pos)
                break

            if 'T=' in line:
                try:
                    parts = line.split()
                    
                    step = int(parts[0])
                    T = float(parts[2])
                    Epot = float(parts[8])
                    Ekin = float(parts[10])
                    Etot = Epot + Ekin

                    # SCF convergence check
                    # Diff_total_energy, diff_band_structure_energy < scf_thr
                    if (
                        self.check_convergence in (True, 'rigorous')
                        and self.prev_line.strip()
                    ):
                        try:
                            scf_parts = self.prev_line[4:].split()
                            dE = float(scf_parts[2])
                            deps = float(scf_parts[3])
                        except (IndexError, ValueError):
                            if self.check_convergence == 'rigorous':
                                raise
                            pass
                        else:
                            if abs(dE) > self.scf_thr or abs(deps) > self.scf_thr:
                                logging.error(f"SCF not converged at step={step}.")
                                return DFTStatus.NOT_CONVERGED_ERROR
                    
                    # skip logging if not at the specified interval
                    if step % self.log_every != 0:
                        self.prev_line = line
                        continue

                    log_file.write(
                        "{:<10.4f} {:12.4f} {:12.4f} {:12.4f} {:12.4f}\n".format(
                            self.cur_time, Etot, Epot, Ekin, T
                        )
                    )
                    log_file.flush()
                    # update
                    self.cur_time += self.md_dt * self.log_every * 1e-3
                except Exception as e:
                    logging.error("Error occurred while processing VASP output."
                                  f"Line: {line.strip()}, Error: {e}")
                    return DFTStatus.UNKNOWN_ERROR
            self.prev_line = line

        return DFTStatus.NORMAL

    def monitor_openmx(self, monitor_file: io.TextIOWrapper, log_file: io.TextIOWrapper):
        while True:
            cur_pos = monitor_file.tell()
            line = monitor_file.readline()
            if not line:
                break
            if not line.endswith('\n'):
                monitor_file.seek(cur_pos)
                break

            if not line.strip():
                continue

            try:
                parts = line.split()

                step = int(parts[0])
                Epot = float(parts[14]) * ase.units.Hartree
                Ekin = float(parts[13]) * ase.units.Hartree
                Etot = float(parts[15]) * ase.units.Hartree
                T = float(parts[18])

                # skip logging if not at the specified interval
                if step % self.log_every != 0:
                    continue

                log_file.write(
                    "{:<10.4f} {:12.4f} {:12.4f} {:12.4f} {:12.4f}\n".format(
                        self.cur_time, Etot, Epot, Ekin, T
                    )
                )
                log_file.flush()
                # update
                self.cur_time += self.md_dt * self.log_every * 1e-3
            except Exception as e:
                logging.error("Error occurred while processing OpenMX output."
                              f"Line: {line.strip()}, Error: {e}")
                return DFTStatus.UNKNOWN_ERROR

        return DFTStatus.NORMAL
        
def run_software(
    software: str,
    nprocs: int,
    monitor: Callable | None = None,
    **kwargs: Any,
) -> None:
    """Run the specified software with appropriate settings.

    Notes: 
        Do not use logging in this function unless you know exactly what you are doing.
        It may be called in subprocesses.

    Args:
        software: Name of the software to run (e.g., 'vasp').
        nprocs: Number of MPI processes to use.
        monitor: Optional callback function to monitor the calculation progress.
    """

    env = os.environ.copy()
    threads = env.get("OMP_NUM_THREADS", "1")
    if "omp" in kwargs and kwargs["omp"] is not None:
        threads = str(kwargs["omp"])
        env["OMP_NUM_THREADS"] = threads
        env["MKL_NUM_THREADS"] = threads
        env["OPENBLAS_NUM_THREADS"] = threads
        env["NUMEXPR_NUM_THREADS"] = threads
    
    cmd_head = set_cmd_head(env, nprocs, int(threads))
    
    if software == 'vasp':
        cmd = cmd_head + run_vasp(nprocs, **kwargs)
    elif software == 'openmx':
        if 'postprocess' in kwargs and kwargs['postprocess']:
            cmd = cmd_head + [str(nprocs), 'openmx_postprocess', 'qdyn.dat']
        else:
            cmd = cmd_head + [str(nprocs), 'openmx', 'qdyn.dat']
    elif software == 'elpa_worker':
        assert 'args' in kwargs
        cmd = cmd_head + [str(nprocs), 'elpa_worker']
        for k, v in kwargs['args'].items():
            cmd.extend([f'--{k}', str(v)])
    else:
        cmd = cmd_head + [software]
    

    if monitor is None:
        result = subprocess.run(cmd, env=env)
        returncode = result.returncode
    else:
        process = subprocess.Popen(cmd, env=env)
        while True:
            if process.poll() is not None:
                break
            dftstatus = monitor()
            if dftstatus and dftstatus != DFTStatus.NORMAL:
                process.terminate()
                raise RuntimeError(f"DFT calculation failed with status: {dftstatus}")
            time.sleep(30)

        final_status = monitor()
        if final_status and final_status != DFTStatus.NORMAL:
            process.terminate()
            raise RuntimeError(f"DFT calculation failed with status: {final_status}")
        returncode = process.wait()


    if returncode != 0:
        # Read queue.err for real error details
        err_hint = ""
        if os.path.isfile("queue.err"):
            with open("queue.err") as f:
                lines = [l.strip() for l in f.readlines() if l.strip()]
                err_hint = "; ".join(lines[-5:]) if lines else ""
        raise RuntimeError(
            f"{software} exited with code {returncode}. "
            f"Last queue.err lines: {err_hint or '(empty)'}"
        )
        
    # post software running
    if software == 'openmx':
        if 'cell' in kwargs and kwargs['cell'] is not None:
            fname = STRU2_FNAME_MAPPING[software]
            stru = read_stru(stru_format='xyz', stru_file=fname.split('.')[0] + '.xyz')
            stru.set_cell(kwargs['cell'])
            stru.set_pbc([True, True, True])
            write_stru(fname, stru, STRU2_FORMAT_MAPPING[software])

def run_vasp(
    nprocs: int, 
    is_alle: bool | None = False, 
    **kwargs: Any
):
    """Run VASP calculation using mpirun.

    Args:
        nprocs: Number of MPI processes
        is_alle: Whether to use all-electron VASP (vasp_ae)
    """
    # Check if using all-electron VASP
    if is_alle:
        vasp_exe = 'vasp_ae'
    else:
        # Read KPOINTS file to determine K-point count
        kpoints_file = Path('KPOINTS')
        if not kpoints_file.exists():
            raise FileNotFoundError("KPOINTS file not found")

        # Read K-point numbers in three directions from line 4
        lines = kpoints_file.read_text().strip().split('\n')
        kx, ky, kz = map(int, lines[3].split())

        # Use vasp_gam for single K-point, otherwise vasp_std
        if kx == 1 and ky == 1 and kz == 1:
            vasp_exe = 'vasp_gam'
        else:
            vasp_exe = 'vasp_std'

    # Launch VASP
    cmd = [vasp_exe]

    return cmd

def set_cmd_head(env: dict[str, Any], tasks: int, threads: int = 1):
    if _SRUN:
        return ['srun', '--mpi=pmi2', 
                '-n', str(tasks), '-c', str(threads),
                '--exact', '--cpu-bind=cores']
    for k, v in _INTEL_MPI_ENVS:
        env.setdefault(k, v)
    return ['mpirun', '-np', str(tasks)]
