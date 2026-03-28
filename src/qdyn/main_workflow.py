import asyncio
from copy import deepcopy
import json
import shutil
from pathlib import Path
import logging
import io
import os
import sqlite3
import subprocess
import uuid
import yaml
from typing import Optional, Tuple, Dict, List, Literal

from ase import Atoms
import ase.io
from jobflow.core.job import Job
from jobflow.core.flow import Flow
from jobflow_remote import SETTINGS, set_run_config, submit_flow
from jobflow_remote.config.base import ExecutionConfig
from jobflow_remote import JobController

from .input import InputT
from .tools.nvt import qdyn_nvt
from .tools.nve import qdyn_nve
from .tools.scf import qdyn_scf
from .tools.prepare_namd import qdyn_pre_namd
from .tools.namd import qdyn_namd


class ValidationError(Exception):
    """Input parameters or steps are invalid."""

    pass


class ConfigError(Exception):
    """Server-side qdyn.yaml configuration is missing or incomplete."""

    pass


class ResumeError(Exception):
    """Resume failed: previous task/job not found or has no output."""

    pass


class QueryError(Exception):
    """Error during querying job status or output."""

    pass


# States that can be stopped via jc.stop_job()
# States where the job has been submitted to the compute queue and can be cancelled.
# WAITING and READY jobs are not yet on the queue, so they cannot (and need not) be stopped.
_STOPPABLE_STATES = {
    "SUBMITTED",
    "CHECKED_OUT",
    "UPLOADED",
    "BATCH_SUBMITTED",
    "BATCH_RUNNING",
    "RUNNING",
    "RUN_FINISHED",
    "DOWNLOADED",
}


class MainWorkflow:

    def __init__(self, config_path: Optional[str] = None):
        self.config, self.jf_config = self._load_config(config_path)
        self.task_ids: List[str] = []
        # {'task_id': {'step': [job_uuid1, job_uuid2, ...]}}
        self.job_ids: Dict[str, Dict[str, List[str]]] = {}
        self.jc: Optional[JobController] = None

    def __del__(self):
        jc = getattr(self, "jc", None)
        if jc is not None:
            jc.close()

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    @staticmethod
    def _load_config(config_path: Optional[str]) -> Tuple[Dict, Dict]:

        path = config_path or os.environ.get('QDYN_CONFIG') or 'config/qdyn.yaml'
        path = os.path.abspath(path)
        if not os.path.exists(path):
            raise ConfigError(
                f"QDYN config file not found: {path}\n"
                f"Create config/qdyn.yaml or set the QDYN_CONFIG environment variable."
            )
        with open(path) as f:
            cfg = yaml.safe_load(f)
        logging.info(f"Loaded config from {path}.")

        path = cfg.get('basic', {}).get('jf_project_path', '')
        if path and os.path.exists(path):
            with open(path) as f:
                jf_cfg = yaml.safe_load(f)
            logging.info(f"Found jobflow-remote project config at {path}.")
        else:
            raise ConfigError(
                f"Jobflow-remote project config not found: {path}\n"
                f"Set basic.jf_project_path in qdyn.yaml to a valid path."
            )
        return cfg, jf_cfg

    def _get_config(self, *keys: str):
        """Traverse self.config by key path, raising ConfigError if any key is missing.

        Usage: self._get_config('nvt', 'vasp', 'nodes')
        is equivalent to self.config['nvt']['vasp']['nodes']
        but raises ConfigError with a clear message on KeyError.
        """
        node = self.config
        for i, key in enumerate(keys):
            if not isinstance(node, dict) or key not in node:
                path = '.'.join(keys[: i + 1])
                raise ConfigError(f"Missing '{path}' in qdyn.yaml")
            node = node[key]
        return node

    def _configure_jobflow_remote(self) -> None:
        """Apply optional jobflow-remote settings from qdyn.yaml before first use."""
        basic_cfg = self.config.get('basic', {})
        project_path = basic_cfg.get('jf_project_path', '')
        project_name = basic_cfg.get('jf_project_name', '')
        if not project_path or not os.path.exists(project_path):
            raise ConfigError(
                f"Jobflow-remote project config not found: {project_path}\n"
                f"Set basic.jf_project_path in qdyn.yaml to a valid path."
            )
        if not project_name:
            raise ConfigError(
                f"Jobflow-remote project name not specified in qdyn.yaml.\n"
                f"Set basic.jf_project_name to the project name defined in your jobflow-remote config."
            )

        SETTINGS.projects_folder = str(Path(project_path).parent.expanduser().resolve())
        SETTINGS.project = project_name

    def _ensure_job_controller(self) -> JobController:
        """Initialize the jobflow-remote controller on demand."""
        if self.jc is None:
            try:
                self._configure_jobflow_remote()
                self.jc = JobController.from_project_name()
            except Exception as exc:
                raise ConfigError(
                    "Failed to initialize jobflow-remote. "
                    "Set basic.jf_project_path/jf_project_name in qdyn.yaml "
                    "or configure ~/.jfremote before using remote job features."
                ) from exc
        return self.jc

    # ------------------------------------------------------------------
    # Pre-flight validation
    # ------------------------------------------------------------------

    def _validate_input(
        self,
        input: InputT,
        method: str,
        stru: Optional[str],
        stru_format: str,
        resume: bool,
        prev_task_id: str,
    ) -> None:
        """Validate inputs before building the workflow. Raises
        ValidationError, ResumeError, or NotImplementedError with a
        clear message."""
        software = input.basic_input.software
        if not (software == 'vasp' and method == 'namd'):
            raise NotImplementedError(
                f"Currently only the combination of software='vasp' and method='namd' is supported.\n"
                f"Got software='{software}', method='{method}'."
            )

        # --- steps ---
        if not input.steps:
            raise ValidationError(
                "input.steps is empty; at least one step is required."
            )

        valid_steps = {'nvt', 'nve', 'scf', 'pre_namd', 'namd'}
        unknown = set(input.steps) - valid_steps  # type: ignore
        if unknown:
            raise ValidationError(
                f"Unknown step(s): {unknown}. Valid steps: {sorted(valid_steps)}"
            )

        if method == 'namd':
            key_map = {'nvt': 0, 'nve': 1, 'scf': 2, 'pre_namd': 3, 'namd': 4}
            step_int = sorted(key_map[s] for s in input.steps)
            for i in range(1, len(step_int)):
                if step_int[i] != step_int[i - 1] + 1:
                    raise ValidationError(
                        f"Steps must be contiguous. Got: {input.steps}"
                    )
        else:
            raise NotImplementedError(f"Method '{method}' is not supported yet.")

        # --- resume ---
        if resume:
            if not prev_task_id:
                raise ValidationError("prev_task_id must be provided when resume=True.")
            if prev_task_id not in self.task_ids:
                raise ResumeError(f"Previous task '{prev_task_id}' not found.")

        if stru:
            try:
                ase.io.read(io.StringIO(stru), format=stru_format, index=':')
            except Exception as exc:
                raise ValidationError(
                    f"Provided structure string could not be parsed "
                    f"by ASE with format '{stru_format}'."
                ) from exc

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def main_workflow(
        self,
        input: InputT,
        method: Literal['namd', 'n2amd'] = 'namd',
        stru: Optional[str] = '',
        stru_format: str = 'vasp',
        resume: bool = False,
        prev_task_id: str = '',
    ) -> Dict[str, List[Job | Flow]]:
        '''
        Notice: assume the config is valid,
                no error handling for missing config entries.
        '''

        # basic keys
        jobs: Dict[str, List[Job | Flow]] = {}
        software = input.basic_input.software
        flag = ''

        # pre-flight validation
        self._validate_input(input, method, stru, stru_format, resume, prev_task_id)

        if method == 'namd':
            key_map = {'nvt': 0, 'nve': 1, 'scf': 2, 'pre_namd': 3, 'namd': 4}
            inv_map = {v: k for k, v in key_map.items()}
            step_int = [key_map[step] for step in input.steps]
            step_int.sort()
            first_step = inv_map[step_int[0]]
        else:
            raise NotImplementedError(f"Method '{method}' is not supported yet.")

        # step 1: NVT
        if ('nvt' in input.steps or flag == 'gen_input_nvt') and input.nvt_input is not None:
            prev_step = ''
            next_step = 'nve'
            if prev_step in input.steps:
                structure = jobs[prev_step][0].output['stru']
            elif first_step == 'nvt' and resume:
                try:
                    prev_job_uuid = self.job_ids[prev_task_id][prev_step][0]
                    structure = self.get_job_output(prev_job_uuid)['stru']
                except Exception as exc:
                    raise ResumeError(
                        f"Previous job for step '{prev_step}' not found or has no output. "
                        f"Cannot resume nvt."
                    ) from exc
            elif stru:
                structure = ase.io.read(io.StringIO(stru), format=stru_format).todict() # type: ignore
            else:
                raise ValidationError(
                    "No structure provided for the nvt step. \n"
                    "Provide a structure string or set resume=True with a valid prev_task_uuid."
                )

            nodes = (
                input.nvt_input.nodes
                if input.nvt_input.nodes is not None
                else self.config['nvt'][software]['nodes']
            )
            assert nodes > 0, "[NVT] nodes must be a positive integer or omitted to use the default."
            ntasks_per_node = self.config['nvt'][software]['ntasks_per_node']
            cpus_per_task = self.config['nvt'][software]['cpus_per_task']
            pp_path = str(Path(self.config['pp_path'][software]).expanduser().resolve())
            orb_path = str(Path(self.config['orb_path'][software]).expanduser().resolve())

            job_nvt = qdyn_nvt(
                software=software,
                parameters=input.nvt_input,
                pp_path=pp_path,
                orb_path=orb_path,
                structure=structure,
                nodes=nodes,
                ntasks_per_node=ntasks_per_node,
                cpus_per_task=cpus_per_task,
                plot=input.basic_input.plot,
                prepare_input_only=bool(flag),
            )
            job_nvt = set_run_config(
                job_nvt,
                exec_config=ExecutionConfig(
                    modules=self.config['modules'][software],
                    export=self.config['export'][software],
                    pre_run=self.config['pre_run'][software],
                    post_run=None,
                ),
                resources={
                    **self.jf_config['workers']['local_slurm'].get('resources', {}),
                    'partition': self.config['machine']['partition'],
                    **self.config['nvt'][software],
                    'nodes': nodes,
                },
            )
            jobs['nvt'] = [job_nvt]

            # update flag
            is_last_step = (True if next_step not in input.steps and 'nvt' in input.steps
                            else False)
            if is_last_step:
                flag = f'gen_input_{next_step}'

        # step 2: NVE
        if ('nve' in input.steps or flag == 'gen_input_nve') and input.nve_input is not None:
            prev_step = 'nvt'
            next_step = 'scf'
            if prev_step in input.steps:
                structure = jobs[prev_step][0].output['stru']
            elif first_step == 'nve' and resume:
                try:
                    prev_job_uuid = self.job_ids[prev_task_id][prev_step][0]
                    structure = self.get_job_output(prev_job_uuid)['stru']
                except Exception as exc:
                    raise ResumeError(
                        f"Previous job for step '{prev_step}' not found or has no output. "
                        f"Cannot resume nve."
                    ) from exc
            elif stru:
                structure = ase.io.read(io.StringIO(stru), format=stru_format).todict() # type: ignore
            else:
                raise ValidationError(
                    "No structure provided for NVE step. \n"
                    "Provide a structure string or set resume=True with a valid prev_task_id."
                )

            nodes = (
                input.nve_input.nodes
                if input.nve_input.nodes is not None
                else self.config['nve'][software]['nodes']
            )
            assert nodes > 0, "[NVE] nodes must be a positive integer or omitted to use the default."
            ntasks_per_node = self.config['nve'][software]['ntasks_per_node']
            cpus_per_task = self.config['nve'][software]['cpus_per_task']
            pp_path = str(Path(self.config['pp_path'][software]).expanduser().resolve())
            orb_path = str(Path(self.config['orb_path'][software]).expanduser().resolve())

            job_nve = qdyn_nve(
                software=software,
                parameters=input.nve_input,
                pp_path=pp_path,
                orb_path=orb_path,
                structure=structure,
                nodes=nodes,
                ntasks_per_node=ntasks_per_node,
                cpus_per_task=cpus_per_task,
                plot=input.basic_input.plot,
                prepare_input_only=bool(flag),
            )
            job_nve = set_run_config(
                job_nve,
                exec_config=ExecutionConfig(
                    modules=self.config['modules'][software],
                    export=self.config['export'][software],
                    pre_run=self.config['pre_run'][software],
                    post_run=None,
                ),
                resources={
                    **self.jf_config['workers']['local_slurm'].get('resources', {}),
                    'partition': self.config['machine']['partition'],
                    **self.config['nve'][software],
                    'nodes': nodes,
                },
            )
            jobs['nve'] = [job_nve]

            # update flag
            is_last_step = (True if next_step not in input.steps and 'nve' in input.steps
                            else False)
            if is_last_step:
                flag = f'gen_input_{next_step}'

        # step 3: SCF
        if ('scf' in input.steps or flag == 'gen_input_scf') and input.scf_input is not None:
            if software == 'abacus':
                # no need for scf calc if using abacus
                pass
            else:
                prev_step = 'nve'
                next_step = 'pre_namd'
                if prev_step in input.steps:
                    structures = jobs[prev_step][0].output['strus']
                elif first_step == 'scf' and resume:
                    try:
                        prev_job_uuid = self.job_ids[prev_task_id][prev_step][0]
                        structures = self.get_job_output(prev_job_uuid)['strus']
                    except Exception as exc:
                        raise ResumeError(
                            f"Previous job for step '{prev_step}' not found or has no output. "
                            f"Cannot resume scf."
                        ) from exc
                elif stru:
                    strus_ase = ase.io.read(io.StringIO(stru), format=stru_format, index=':')
                    structures = [s.todict() for s in strus_ase] # type: ignore
                else:
                    raise ValidationError(
                        "SCF step requires NVE output. Include 'nve' in steps, "
                        "or set resume=True with a prev_task_id that has NVE results."
                    )

                nodes = (
                    input.scf_input.nodes
                    if input.scf_input.nodes is not None
                    else self.config['scf'][software]['nodes']
                )
                assert nodes > 0, "[SCF] nodes must be a positive integer or omitted to use the default."
                ntasks_per_node = self.config['scf'][software]['ntasks_per_node']
                cpus_per_task = self.config['scf'][software]['cpus_per_task']
                pp_path = str(Path(self.config['pp_path'][software]).expanduser().resolve())
                orb_path = str(Path(self.config['orb_path'][software]).expanduser().resolve())

                jobs_scf = qdyn_scf(
                    software=software,
                    parameters=input.scf_input,
                    pp_path=pp_path,
                    orb_path=orb_path,
                    structures=structures, # type: ignore
                    nodes=nodes,
                    ntasks_per_node=ntasks_per_node,
                    cpus_per_task=cpus_per_task,
                    plot=input.basic_input.plot,
                    prepare_input_only=bool(flag),
                )
                for i in range(len(jobs_scf)):
                    jobs_scf[i] = set_run_config(
                        jobs_scf[i],
                        exec_config=ExecutionConfig(
                            modules=self.config['modules'][software],
                            export=self.config['export'][software],
                            pre_run=self.config['pre_run'][software],
                            post_run=None,
                        ),
                        resources={
                            **self.jf_config['workers']['local_slurm'].get('resources', {}),
                            'partition': self.config['machine']['partition'],
                            **self.config['scf'][software],
                            'nodes': nodes,
                        },
                    )
                jobs['scf'] = jobs_scf

                # update flag
                is_last_step = (True if next_step not in input.steps and 'scf' in input.steps
                                else False)
                if is_last_step:
                    flag = f'gen_input_{next_step}'

        # step 4: PRE_NAMD
        if ('pre_namd' in input.steps or flag == 'gen_input_pre_namd') and input.prenamd_input is not None:
            prev_step = 'scf' if software != 'abacus' else 'nve'
            next_step = 'namd'
            if prev_step in input.steps:
                run_dirs = []
                for idx in range(len(jobs[prev_step])):
                    run_dirs.append(jobs[prev_step][idx].output['run_dir'])
            elif first_step == 'pre_namd' and resume:
                try:
                    prev_jobs = self.job_ids[prev_task_id][prev_step]
                    run_dirs = []
                    for prev_job_uuid in prev_jobs:
                        output = self.get_job_output(prev_job_uuid)
                        run_dirs.append(output['run_dir'])
                except Exception as exc:
                    raise ResumeError(
                        f"Previous job(s) for step '{prev_step}' not found or has no output. "
                        f"Cannot resume pre_namd."
                    ) from exc
            else:
                raise ValidationError(
                    f"PRE_NAMD step requires '{prev_step}' output. Include '{prev_step}' "
                    f"in steps, or set resume=True with a prev_task_id that has "
                    f"'{prev_step}' results."
                )

            ncpus = self.config['machine']['cpus_per_node']
            job_pre_namd = qdyn_pre_namd(
                software=software,
                parameters=input.prenamd_input,
                run_dirs=run_dirs,
                nproc=ncpus // 4,
                plot=input.basic_input.plot,
                prepare_input_only=bool(flag),
            )
            job_pre_namd = set_run_config(
                job_pre_namd,
                exec_config=ExecutionConfig(
                    modules=self.config['modules']['python'],
                    export={
                        **self.config['export']['python'], 
                        'OMP_NUM_THREADS': '4'
                    },
                    pre_run=self.config['pre_run']['python'],
                    post_run=None,
                ),
                resources={
                    **self.jf_config['workers']['local_slurm'].get('resources', {}),
                    'partition': self.config['machine']['partition'],
                    'nodes': 1,
                    'ntasks_per_node': 1,
                    'cpus_per_task': ncpus,
                },
            )
            jobs['pre_namd'] = [job_pre_namd]

            # update flag
            is_last_step = (True if next_step not in input.steps and 'pre_namd' in input.steps
                            else False)
            if is_last_step:
                flag = f'gen_input_{next_step}'

        # step 4: NAMD
        if ('namd' in input.steps or flag == 'gen_input_namd') and input.namd_input is not None:
            prev_step = 'pre_namd'
            next_step = ''
            if prev_step in input.steps:
                prev_output = jobs[prev_step][0].output
            elif first_step == 'namd' and resume:
                try:
                    prev_job_uuid = self.job_ids[prev_task_id][prev_step][0]
                    prev_output = self.get_job_output(prev_job_uuid)
                except Exception as exc:
                    raise ResumeError(
                        f"Previous job for step '{prev_step}' not found or has no output. "
                        f"Cannot resume namd."
                    ) from exc
            else:
                raise ValidationError(
                    "NAMD step requires PRE_NAMD output. Include 'pre_namd' in steps, "
                    "or set resume=True with a prev_task_id that has PRE_NAMD results."
                )
            eigtxt = prev_output['EIGTXT']
            natxt = prev_output['NATXT']
            dephtime = prev_output['DEPHTIME']

            if input.namd_input.surface_hopping == 'FSSH':
                nodes = 1
                ntasks_per_node = 1
                cpus_per_task = self.config['machine']['cpus_per_node']
            else:
                nodes = (
                    input.namd_input.nodes if input.namd_input.nodes is not None else 1
                )
                assert nodes > 0, "[NAMD] nodes must be a positive integer or omitted to use the default."
                ntasks_per_node = self.config['machine']['cpus_per_node']
                cpus_per_task = 1

            job_namd = qdyn_namd(
                parameters=input.namd_input,
                eigtxt=eigtxt,
                natxt=natxt,
                dephtime=dephtime,
                nodes=nodes,
                ntasks_per_node=ntasks_per_node,
                cpus_per_task=cpus_per_task,
                plot=input.basic_input.plot,
                prepare_input_only=bool(flag),
            )
            job_namd = set_run_config(
                job_namd,
                exec_config=ExecutionConfig(
                    modules=self.config['modules']['namd'],
                    export={
                        **self.config['export']['namd'],
                        'OMP_NUM_THREADS': str(cpus_per_task),
                    },
                    pre_run=self.config['pre_run']['namd'],
                    post_run=None,
                ),
                resources={
                    **self.jf_config['workers']['local_slurm'].get('resources', {}),
                    'partition': self.config['machine']['partition'],
                    'nodes': nodes,
                    'ntasks_per_node': ntasks_per_node,
                    'cpus_per_task': cpus_per_task,
                },
            )
            jobs['namd'] = [job_namd]

            # update flag
            is_last_step = (True if next_step not in input.steps and 'namd' in input.steps
                            else False)
            if is_last_step:
                flag = f'gen_input_{next_step}'

        if not jobs:
            raise ValidationError(
                "No valid steps with input provided. Please check your input and config."
            )

        return jobs


    def submit(
        self,
        input: InputT,
        method: Literal['namd', 'n2amd'] = 'namd',
        stru: Optional[str] = '',
        stru_format: str = 'vasp',
        resume: bool = False,
        prev_task_id: str = '',
    ) -> Tuple[str, Dict[str, List[str]]]:
        self._ensure_job_controller()

        jobs = self.main_workflow(
            input=input,
            method=method,
            stru=stru,
            stru_format=stru_format,
            resume=resume,
            prev_task_id=prev_task_id,
        )
        jobs_flatten = []
        for job_list in jobs.values():
            jobs_flatten.extend(job_list)
        flow = Flow(jobs_flatten)
        db_ids = submit_flow(flow, worker='local_slurm')

        task_id = flow.uuid
        job_ids = {}
        for key, value in jobs.items():
            job_ids[key] = [v.uuid for v in value]
        self.job_ids[task_id] = job_ids

        self.task_ids.append(task_id)

        return task_id, job_ids


    def list_tasks(self) -> List[str]:
        """Return all task IDs known to this instance (local-memory view)."""
        return list(self.task_ids)


    def list_task_jobs(self, task_id: str) -> Dict[str, List[str]]:
        """Return job UUIDs grouped by step for a given task."""
        if task_id not in self.task_ids:
            raise ValidationError(f"Task '{task_id}' not found.")
        return self.job_ids[task_id]


    def get_job_status(self, job_uuid: str) -> str:
        """Query job status."""
        jc = self._ensure_job_controller()
        try:
            job_info = jc.get_job_info(job_id=job_uuid)
            assert job_info is not None
        except:
            raise QueryError(f"Job '{job_uuid}' not found.")
        return job_info.state.value


    def get_job_output(self, job_uuid: str):
        """Retrieve a completed job's output from the jobstore."""
        jc = self._ensure_job_controller()

        status = self.get_job_status(job_uuid)
        if status != 'COMPLETED':
            raise QueryError(
                f"Job '{job_uuid}' is not completed. Current status: {status}"
            )
        out = jc.get_job_output(job_id=job_uuid)
        return out


    def restore_from_db(self, conn: sqlite3.Connection) -> int:
        """Restore task_ids and job_ids from the SQLite database.
        Returns the number of tasks restored."""
        rows = conn.execute("SELECT task_id, job_ids FROM task_owners").fetchall()
        for row in rows:
            tid = row["task_id"]
            self.task_ids.append(tid)
            self.job_ids[tid] = json.loads(row["job_ids"])
        return len(rows)

    def stop_task_jobs(self, task_id: str) -> Dict[str, List[str] | List[Dict[str, str]]]:
        """
        Stop all stoppable jobs for a task with detailed per-job results.

        Returns a dictionary with keys: 'stopped', 'skipped', 'failed'
        where each key maps to a list of job UUIDs or failed job info.
        """
        # Validate task existence first (may raise ValidationError)
        job_ids = self.list_task_jobs(task_id)

        jc = self._ensure_job_controller()

        stopped: List[str] = []
        skipped: List[str] = []
        failed: List[Dict[str, str]] = []

        # Flatten step -> [job_uuid] to a single list
        jobs_flatten: list[str] = []
        for job_list in job_ids.values():
            jobs_flatten.extend(job_list)

        for job_uuid in jobs_flatten[::-1]:  # reverse order to respect dependencies
            # Query the current state of the job
            try:
                job_info = jc.get_job_info(job_id=job_uuid)
                if job_info is None:
                    # Job not found - assume it's already been cleaned up
                    skipped.append(job_uuid)
                    continue
                raw_state = job_info.state.value
            except Exception as exc:
                # Query failed - this is a real error
                failed.append({"uuid": job_uuid, "error": f"Query failed: {exc}"})
                continue

            # Only stop jobs that are in a stoppable state
            if raw_state not in _STOPPABLE_STATES:
                skipped.append(job_uuid)
                continue

            # Attempt to stop the job
            try:
                jc.stop_job(job_id=job_uuid)
                stopped.append(job_uuid)
            except Exception as exc:
                failed.append({"uuid": job_uuid, "error": str(exc)})

        return {
            "stopped": stopped,
            "skipped": skipped,
            "failed": failed
        }

    def delete_task_record(self, task_id: str) -> None:
        """
        Delete a task's local records after ensuring all stoppable jobs are stopped.

        If any jobs fail to stop, raises RuntimeError with details.
        """
        # First try to stop all stoppable jobs
        stop_result = self.stop_task_jobs(task_id)

        # If any stop failed, abort deletion
        if stop_result["failed"]:
            failed_details = "; ".join(
                f"{f['uuid']}: {f['error']}" for f in stop_result["failed"]
            )
            raise RuntimeError(
                f"Cannot delete task: {len(stop_result['failed'])} job(s) failed to stop. "
                f"Details: {failed_details}"
            )

        # Delete local database records
        from .database import qdyndb
        qdyndb.delete_task_record(task_id)

        # Remove from in-memory tracking
        if task_id in self.task_ids:
            self.task_ids.remove(task_id)
        if task_id in self.job_ids:
            del self.job_ids[task_id]
