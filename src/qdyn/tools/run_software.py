from enum import Enum
import io
import logging
import math
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Literal

class DFTStatus(Enum):
    NORMAL = 0
    NOT_CONVERGED_ERROR = 1
    UNKNOWN_ERROR = 2


class MDProgressMonitor:

    MONITOR_FNAME_MAPPING = {
        'vasp': 'OSZICAR',
    }

    def __init__(self, 
                 software: Literal['vasp'], 
                 nstep: int, 
                 scf_thr: float = 1e-6,
                 md_dt: float = 1.0,
                 log_every: int = 1,
                 check_convergence: bool = True,
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
            self.log_file = open('qdyn_md.log', 'w')
            # Write header
            self.log_file.write(
                f"Step: {self.nstep // self.log_every}, Interval: {self.log_every}\n"
                f"Time[ps]      Etot[eV]     Epot[eV]     Ekin[eV]    T[K]\n"
            )
            self.log_file.flush()

        if self.software == 'vasp':
            status = self.monitor_vasp(self.monitor_file, self.log_file)
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
                    if self.check_convergence and self.prev_line.strip():
                        try:
                            scf_parts = self.prev_line[4:].split()
                            dE = float(scf_parts[2])
                            deps = float(scf_parts[3])
                        except (IndexError, ValueError):
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
                        "{:<10.4f} {:12.2f} {:12.2f} {:12.2f} {:12.2f}\n".format(
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


def run_software(
    software: str,
    nprocs: int,
    monitor: Callable | None = None,
    **kwargs: Any,
) -> None:
    """Run the specified software with appropriate settings.

    Args:
        software: Name of the software to run (e.g., 'vasp').
        nprocs: Number of MPI processes to use.
        monitor: Optional callback function to monitor the calculation progress.
    """

    if software == 'vasp':
        run_vasp(nprocs, monitor=monitor, **kwargs)
    else:
        raise NotImplementedError(f"Software '{software}' is not supported yet.")


def run_vasp(
    nprocs: int, 
    is_alle: bool | None = False, 
    monitor: Callable | None = None,
    **kwargs: Any
) -> None:
    """Run VASP calculation using mpirun.

    Args:
        nprocs: Number of MPI processes
        is_alle: Whether to use all-electron VASP (vasp_ae)
        monitor: Optional callback function to monitor the calculation progress
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
    env = os.environ.copy()
    if "omp" in kwargs and kwargs["omp"] is not None:
        env["OMP_NUM_THREADS"] = str(kwargs["omp"])

    if monitor is None:
        result = subprocess.run(
            ['mpirun', '-np', str(nprocs), vasp_exe],
            env=env,
        )
        returncode = result.returncode
    else:
        vasp_process = subprocess.Popen(
            ['mpirun', '-np', str(nprocs), vasp_exe],
            env=env,
        )
        while True:
            if vasp_process.poll() is not None:
                break
            dftstatus = monitor()
            if dftstatus and dftstatus != DFTStatus.NORMAL:
                vasp_process.terminate()
                raise RuntimeError(f"DFT calculation failed with status: {dftstatus}")
            time.sleep(30)

        final_status = monitor()
        if final_status and final_status != DFTStatus.NORMAL:
            vasp_process.terminate()
            raise RuntimeError(f"DFT calculation failed with status: {final_status}")
        returncode = vasp_process.wait()


    if returncode != 0:
        # Read queue.err for real error details
        err_hint = ""
        if os.path.isfile("queue.err"):
            with open("queue.err") as f:
                lines = [l.strip() for l in f.readlines() if l.strip()]
                err_hint = "; ".join(lines[-5:]) if lines else ""
        raise RuntimeError(
            f"VASP exited with code {returncode}. "
            f"Last queue.err lines: {err_hint or '(empty)'}"
        )
