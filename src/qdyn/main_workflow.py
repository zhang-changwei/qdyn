import asyncio
from copy import deepcopy
import hashlib
import json
import re
import shutil
from pathlib import Path
import logging
import io
import os
import sqlite3
import subprocess
import tempfile
import uuid
import yaml
from typing import Any, Tuple, Dict, List, Literal

from ase import Atoms
import ase.io
from jobflow.core.job import Job
from jobflow.core.flow import Flow
from jobflow_remote import SETTINGS, set_run_config, submit_flow
from jobflow_remote.config.base import ExecutionConfig
from jobflow_remote import JobController

from .input import InputT
from .params import md_tracks, md_ase_formats

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

_REMOTE_WORKER_TYPES = {"remote", "separated_transfer"}


class MainWorkflow:

    def __init__(self, config_path: str | None = None):
        self.config, self.jf_config = self._load_config(config_path)
        self.task_ids: List[str] = []
        # {'task_id': {'step': [job_uuid1, job_uuid2, ...]}}
        self.job_ids: Dict[str, Dict[str, List[str]]] = {}
        self.jc: JobController | None = None

        # Resolve active pool / worker configuration.
        if 'worker_pools' not in self.config:
            raise ConfigError(
                "Missing 'worker_pools' section in qdyn.yaml. "
                "See config/qdyn.yaml.example for the expected structure."
            )

        self.active_pool_name: str = self.config.get(
            'active_pool', next(iter(self.config['worker_pools']))
        )
        if self.active_pool_name not in self.config['worker_pools']:
            raise ConfigError(
                f"active_pool '{self.active_pool_name}' not found in "
                f"worker_pools section of qdyn.yaml. "
                f"Available: {list(self.config['worker_pools'].keys())}"
            )
        pool_def = self.config['worker_pools'][self.active_pool_name]
        self.pool_worker_cfg: dict = pool_def.get('worker', {})
        self.pool_config: dict = pool_def.get('pool', {})

    def __del__(self):
        jc = getattr(self, "jc", None)
        if jc is not None:
            jc.close()

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    @staticmethod
    def _load_config(config_path: str | None) -> Tuple[Dict, Dict]:

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

        # Validate config format: only pool-based is supported.
        if 'worker_pools' not in cfg:
            raise ConfigError(
                "Missing 'worker_pools' section in qdyn.yaml. "
                "See config/qdyn.yaml.example for the expected structure."
            )
        logging.info("Using pool-based config format (worker_pools).")

        jf_path = cfg.get('basic', {}).get('jf_project_path', '')
        if jf_path and os.path.exists(jf_path):
            with open(jf_path) as f:
                jf_cfg = yaml.safe_load(f)
            logging.info(f"Found jobflow-remote project config at {jf_path}.")
        else:
            raise ConfigError(
                f"Jobflow-remote project config not found: {jf_path}\n"
                f"Set basic.jf_project_path in qdyn.yaml to a valid path."
            )
        return cfg, jf_cfg

    def _resolve_worker_context(
        self, pool_name_override: str | None = None
    ) -> Tuple[str, Dict[str, Any]]:
        """Resolve the effective pool name and worker config.

        Returns (pool_name, worker_cfg) so that callers can build
        ExecutionConfig / resource dicts uniformly.
        """
        pool_name = pool_name_override or self.active_pool_name
        if pool_name not in self.config['worker_pools']:
            raise ValidationError(
                f"Pool '{pool_name}' not found in config. "
                f"Available: {list(self.config['worker_pools'].keys())}"
            )
        return pool_name, self.config['worker_pools'][pool_name].get('worker', {})

    # ------------------------------------------------------------------
    # Pool helpers
    # ------------------------------------------------------------------

    def _resolve_pool_context(
        self, pool_name: str | None = None
    ) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
        """Resolve pool name, worker config, and pool parameters.

        Returns (pool_name, worker_cfg, pool_config).
        """
        name = pool_name or self.active_pool_name
        if name not in self.config['worker_pools']:
            raise ValidationError(
                f"Pool '{name}' not found in config. "
                f"Available: {list(self.config['worker_pools'].keys())}"
            )
        pool_def = self.config['worker_pools'][name]
        return name, pool_def.get('worker', {}), pool_def.get('pool', {})

    def _get_pool_workers(self, pool_name: str | None = None) -> List[str]:
        """Return runtime worker names belonging to a pool.

        Scans jf_config['workers'] for names matching the pattern
        ``{pool_name}_\\d{3,}`` (e.g. local_slurm_001, local_slurm_002).
        Results are sorted lexicographically.
        """
        import re
        name = pool_name or self.active_pool_name
        prefix = f"{name}_"
        pattern = re.compile(rf"^{re.escape(name)}_\d{{3,}}$")
        workers = sorted(
            w for w in self.jf_config.get('workers', {})
            if pattern.match(w)
        )
        return workers

    # ------------------------------------------------------------------
    # Pool occupancy queries (MongoDB)
    # ------------------------------------------------------------------

    # Terminal states: jobs in these states are "done" and no longer occupy a worker.
    # Aligned with jobflow-remote's JobState enum — note that jf-remote has
    # USER_STOPPED but NOT CANCELLED as a job state.  CANCELLED only exists
    # at the QDYN queue level (queued_submissions table), not in MongoDB.
    _TERMINAL_STATES = [
        "COMPLETED", "FAILED", "REMOTE_ERROR", "STOPPED", "USER_STOPPED",
    ]

    def _get_pool_occupancy(self, pool_name: str | None = None) -> Dict[str, int]:
        """Query the number of SUBMITTED+RUNNING jobs per pool worker.

        Returns a dict mapping each pool worker name to its active slot
        count.  Workers with zero active jobs are included with value 0.

        Uses MongoDB aggregation on the jobs collection for accuracy,
        matching the jf-remote Runner's own ``max_jobs`` accounting.
        """
        jc = self._ensure_job_controller()
        pool_workers = self._get_pool_workers(pool_name)
        if not pool_workers:
            return {}

        pipeline = [
            {
                "$match": {
                    "worker": {"$in": pool_workers},
                    "state": {"$in": ["SUBMITTED", "RUNNING"]},
                }
            },
            {
                "$group": {
                    "_id": "$worker",
                    "active_slots": {"$sum": 1},
                }
            },
        ]
        result = {w: 0 for w in pool_workers}
        for doc in jc.jobs.aggregate(pipeline):
            result[doc["_id"]] = doc["active_slots"]
        return result

    def _get_user_occupied_workers(
        self, username: str, pool_name: str | None = None
    ) -> List[str]:
        """Return the list of pool workers currently occupied by *username*.

        A worker is "occupied" if it has at least one non-terminal job
        whose ``job.metadata.qdyn_user`` matches *username*.
        """
        jc = self._ensure_job_controller()
        pool_workers = self._get_pool_workers(pool_name)
        if not pool_workers:
            return []

        pipeline = [
            {
                "$match": {
                    "worker": {"$in": pool_workers},
                    "job.metadata.qdyn_user": username,
                    "state": {"$nin": self._TERMINAL_STATES},
                }
            },
            {
                "$group": {"_id": "$worker"}
            },
        ]
        return [doc["_id"] for doc in jc.jobs.aggregate(pipeline)]

    def _get_free_workers(self, pool_name: str | None = None) -> List[str]:
        """Return pool workers that have zero non-terminal jobs.

        A worker is "free" (idle) when it has no jobs in any non-terminal
        state.  Results are sorted lexicographically, matching the order
        returned by :meth:`_get_pool_workers`.
        """
        jc = self._ensure_job_controller()
        pool_workers = self._get_pool_workers(pool_name)
        if not pool_workers:
            return []

        busy_pipeline = [
            {
                "$match": {
                    "worker": {"$in": pool_workers},
                    "state": {"$nin": self._TERMINAL_STATES},
                }
            },
            {"$group": {"_id": "$worker"}},
        ]
        busy = {doc["_id"] for doc in jc.jobs.aggregate(busy_pipeline)}
        return [w for w in pool_workers if w not in busy]

    def _select_runtime_worker(
        self, username: str, pool_name: str | None = None
    ) -> Tuple[str | None, str]:
        """Select a runtime worker for a new submission.

        Selection logic:
        1. Check whether the pool has any free worker (zero non-terminal
           jobs).  If not, return ``(None, "pool_full")`` -- the caller
           must enqueue the task.
        2. If the user already occupies a worker, submit to that existing
           worker (``"existing"``).  Otherwise allocate a free worker
           (``"new"``).  Each user occupies at most one worker.

        Returns
        -------
        (worker_name, "existing")
            User already has a worker; submit to it.
        (worker_name, "new")
            User has no worker yet; a free worker was allocated.
        (None, "pool_full")
            No free workers in the pool; task must be queued.
        """
        name, _, pool_cfg = self._resolve_pool_context(pool_name)
        pool_workers = self._get_pool_workers(name)
        if not pool_workers:
            logging.warning(
                f"No runtime workers found for pool '{name}'. "
                f"Did you run generate_jf_config.py?"
            )
            return None, "pool_full"

        # 1. Any free worker in the pool?
        free_workers = self._get_free_workers(name)
        if not free_workers:
            logging.info(
                f"No free workers available in pool '{name}' "
                f"(all {len(pool_workers)} workers are busy)."
            )
            return None, "pool_full"

        # 2. Check whether the user already occupies a worker.
        user_workers = self._get_user_occupied_workers(username, name)

        if user_workers:
            # User already has a worker -- route to it.
            logging.info(
                f"User '{username}' already has worker '{user_workers[0]}' "
                f"in pool '{name}' -- submitting to existing worker."
            )
            return user_workers[0], "existing"

        # 3. Allocate a free worker for this user.
        selected = free_workers[0]
        logging.info(
            f"Allocated free worker '{selected}' for user '{username}' "
            f"in pool '{name}'."
        )
        return selected, "new"

    def _get_worker_work_dir(self, worker_name: str) -> str:
        """Return the work_dir for a worker or pool.

        For a runtime worker (e.g. ``local_slurm_001``), reads directly
        from ``jf_config['workers']``.  For a pool name, returns the
        ``work_dir_base`` from the pool config -- this is the shared
        parent directory for all pool workers.
        """
        jf_workers = self.jf_config.get('workers', {})
        if worker_name in jf_workers:
            return jf_workers[worker_name].get('work_dir', '')

        # Pool name: return pool.work_dir_base from qdyn.yaml
        pool_def = self.config['worker_pools'].get(worker_name, {})
        return pool_def.get('pool', {}).get('work_dir_base', '')

    def _get_config(self, worker_name: str, worker_cfg: Dict[str, Any], *keys: str):
        """Traverse worker_cfg by key path, raising ConfigError if missing.

        Usage: self._get_config(worker_name, worker_cfg, 'nvt', 'vasp', 'nodes')
        is equivalent to worker_cfg['nvt']['vasp']['nodes']
        but raises ConfigError with a clear message on KeyError.
        """
        node = worker_cfg
        for i, key in enumerate(keys):
            if not isinstance(node, dict) or key not in node:
                path = '.'.join(keys[: i + 1])
                raise ConfigError(
                    f"Missing '{path}' in worker '{worker_name}' config"
                )
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
    # Worker-aware helpers
    # ------------------------------------------------------------------

    def _get_worker_resources(self, worker_name: str) -> dict:
        """Get jfremote worker resources for the named worker.

        In pool-based mode, *worker_name* might be a pool name (e.g.
        ``local_slurm``) rather than a runtime worker name (e.g.
        ``local_slurm_001``).  When the exact name is not found in
        ``jf_config['workers']``, we fall back to reading worker.resources
        from qdyn.yaml (which is what the jf config generator uses to
        populate each runtime worker's resources).
        """
        jf_workers = self.jf_config.get('workers', {})
        if worker_name in jf_workers:
            return jf_workers[worker_name].get('resources', {})

        # Fallback: pool-based config — use worker.resources from qdyn.yaml
        pool_def = self.config['worker_pools'].get(worker_name, {})
        return pool_def.get('worker', {}).get('resources', {})

    def _get_machine_config(self, worker_name: str, worker_cfg: Dict[str, Any]) -> dict:
        """Get machine config (partition, cpus_per_node, etc.) for the active worker/pool.

        In pool-based format, worker_cfg is pool_worker_cfg which
        contains partition, cpus_per_node, etc. directly.
        """
        return worker_cfg

    def _get_exec_config(
        self, worker_name: str, worker_cfg: Dict[str, Any], software: str, key: str
    ):
        """Get execution config (modules/export/pre_run/pp_path) for the
        current worker/pool and software.

        Reads from worker_cfg.<key>.<software>.
        """
        return worker_cfg.get(key, {}).get(software)

    def _is_remote_worker(self, worker_name: str) -> bool:
        """Check if the named worker is a remote (SSH) worker.

        In pool-based mode, if *worker_name* is a pool name (e.g.
        ``local_slurm``), we check the pool's worker.type from qdyn.yaml.
        """
        jf_workers = self.jf_config.get('workers', {})
        if worker_name in jf_workers:
            return jf_workers[worker_name].get('type') in _REMOTE_WORKER_TYPES

        # Pool name: check the worker's type from qdyn.yaml worker config
        pool_def = self.config['worker_pools'].get(worker_name, {})
        worker_type = pool_def.get('worker', {}).get('type', 'local')
        return worker_type in _REMOTE_WORKER_TYPES

    def _get_ssh_cmd(self, worker_name: str, *args: str) -> list[str]:
        """Build an SSH command list using the active worker's connection config."""
        worker_cfg = self.jf_config['workers'][worker_name]
        host = worker_cfg.get('host', '')
        cmd = ['ssh']
        port = worker_cfg.get('port')
        if port:
            cmd += ['-p', str(port)]
        key = worker_cfg.get('key_filename')
        if key:
            cmd += ['-i', str(key)]
        user = worker_cfg.get('user')
        target = f"{user}@{host}" if user else host
        cmd.append(target)
        cmd.extend(args)
        return cmd

    def _get_scp_cmd(self, worker_name: str, src: str, dst: str) -> list[str]:
        """Build an SCP command list using the active worker's connection config."""
        worker_cfg = self.jf_config['workers'][worker_name]
        host = worker_cfg.get('host', '')
        cmd = ['scp']
        port = worker_cfg.get('port')
        if port:
            cmd += ['-P', str(port)]
        key = worker_cfg.get('key_filename')
        if key:
            cmd += ['-i', str(key)]
        user = worker_cfg.get('user')
        target = f"{user}@{host}" if user else host
        cmd += [src, f"{target}:{dst}"]
        return cmd

    # ------------------------------------------------------------------
    # Pre-flight validation
    # ------------------------------------------------------------------

    def _validate_input(
        self,
        input: InputT,
        method: str,
        stru: str,
        stru_format: str,
        stru_hash: str,
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
            
        if stru_hash:
            # Hash format already validated by InputT.validate_stru_hash (pydantic)
            data_dir = Path(self.config['basic'].get('user_data', 'data/user_data')).resolve()
            stru_path = data_dir / "trajs" / f"{stru_hash}"
            if not stru_path.is_file():
                raise ValidationError(f"Structure with hash '{stru_hash}' not found.")
            ase_format = md_ase_formats.get(stru_format)
            if ase_format is None:
                raise ValidationError(
                    f"Unsupported trajectory format: '{stru_format}'. "
                    f"Supported: {', '.join(md_ase_formats.keys())}"
                )
            try:
                ase.io.read(stru_path, format=ase_format, index=0)
            except Exception as exc:
                raise ValidationError(
                    f"Structure with hash '{stru_hash}' could not be parsed "
                    f"by ASE with format '{ase_format}'."
                ) from exc


    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def main_workflow(
        self,
        input: InputT,
        method: Literal['namd', 'n2amd'] = 'namd',
        stru: str = '',
        stru_format: str = 'vasp',
        stru_hash: str = '',
        resume: bool = False,
        prev_task_id: str = '',
        worker_name: str | None = None,
        worker_cfg: Dict[str, Any] | None = None,
        runtime_worker: str | None = None,
    ) -> Dict[str, List[Job | Flow]]:
        '''
        Notice: assume the config is valid,
                no error handling for missing config entries.

        Parameters
        ----------
        runtime_worker : str, optional
            The actual jf-remote worker name (e.g. ``local_slurm_007``)
            selected at dispatch time.  Used for ``_get_worker_resources()``
            lookups so that resources come from the runtime worker's jf
            config rather than the pool-level fallback.  If None, falls
            back to *worker_name*.
        '''

        # basic keys
        jobs: Dict[str, List[Job | Flow]] = {}
        software = input.basic_input.software
        flag = ''
        effective_worker_name = worker_name or self.active_pool_name
        effective_worker_cfg = worker_cfg or self.pool_worker_cfg
        # For resource lookups, prefer the runtime worker (has exact jf config)
        resource_worker = runtime_worker or effective_worker_name

        # pre-flight validation
        self._validate_input(input, method, stru, stru_format, stru_hash, resume, prev_task_id)

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
                else effective_worker_cfg['nvt'][software]['nodes']
            )
            assert nodes > 0, "[NVT] nodes must be a positive integer or omitted to use the default."
            ntasks_per_node = effective_worker_cfg['nvt'][software]['ntasks_per_node']
            cpus_per_task = effective_worker_cfg['nvt'][software]['cpus_per_task']
            pp_path_raw = self._get_exec_config(
                effective_worker_name, effective_worker_cfg, software, 'pp_path'
            )
            pp_path = str(Path(pp_path_raw).expanduser().resolve()) if pp_path_raw else ''
            orb_path = str(Path(effective_worker_cfg.get('orb_path', {}).get(software, '')).expanduser().resolve())

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
                    modules=self._get_exec_config(effective_worker_name, effective_worker_cfg, software, 'modules'),
                    export=self._get_exec_config(effective_worker_name, effective_worker_cfg, software, 'export'),
                    pre_run=self._get_exec_config(effective_worker_name, effective_worker_cfg, software, 'pre_run'),
                    post_run=None,
                ),
                resources={
                    **self._get_worker_resources(resource_worker),
                    'partition': self._get_machine_config(effective_worker_name, effective_worker_cfg)['partition'],
                    **effective_worker_cfg['nvt'][software],
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
                else effective_worker_cfg['nve'][software]['nodes']
            )
            assert nodes > 0, "[NVE] nodes must be a positive integer or omitted to use the default."
            ntasks_per_node = effective_worker_cfg['nve'][software]['ntasks_per_node']
            cpus_per_task = effective_worker_cfg['nve'][software]['cpus_per_task']
            pp_path_raw = self._get_exec_config(
                effective_worker_name, effective_worker_cfg, software, 'pp_path'
            )
            pp_path = str(Path(pp_path_raw).expanduser().resolve()) if pp_path_raw else ''
            orb_path = str(Path(effective_worker_cfg.get('orb_path', {}).get(software, '')).expanduser().resolve())

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
                    modules=self._get_exec_config(effective_worker_name, effective_worker_cfg, software, 'modules'),
                    export=self._get_exec_config(effective_worker_name, effective_worker_cfg, software, 'export'),
                    pre_run=self._get_exec_config(effective_worker_name, effective_worker_cfg, software, 'pre_run'),
                    post_run=None,
                ),
                resources={
                    **self._get_worker_resources(resource_worker),
                    'partition': self._get_machine_config(effective_worker_name, effective_worker_cfg)['partition'],
                    **effective_worker_cfg['nve'][software],
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
                    # NVE in the same flow: OutputReference resolves to traj path
                    traj_file_path = jobs[prev_step][0].output['traj_file_path']
                    traj_format = input.basic_input.software
                elif first_step == 'scf' and resume:
                    # Resume SCF from a previous task
                    try:
                        prev_job_uuid = self.job_ids[prev_task_id][prev_step][0]
                        nve_output = self.get_job_output(prev_job_uuid)
                        if 'traj_file_path' in nve_output:
                            traj_file_path = nve_output['traj_file_path']
                        else:
                            # NVE output before traj_file_path was added
                            traj_file_path = os.path.join(
                                nve_output['run_dir'],
                                md_tracks[software.lower()],
                            )
                        traj_format = input.basic_input.software
                    except Exception as exc:
                        raise ResumeError(
                            f"Previous job for step '{prev_step}' not found or has no output. "
                            f"Cannot resume scf."
                        ) from exc
                elif stru_hash:
                    data_dir = Path(self.config['basic'].get('user_data', 'data/user_data')).resolve()
                    traj_file_path = str(data_dir / "trajs" / f"{stru_hash}")
                    traj_format = stru_format
                elif stru:
                    # User-provided structure text: write to trajectory file
                    strus_ase = ase.io.read(io.StringIO(stru), format=stru_format, index=':')
                    work_dir = self._get_worker_work_dir(effective_worker_name)

                    if self._is_remote_worker(effective_worker_name):
                        # Remote worker: write locally then scp to remote host
                        import tempfile
                        stru_id = str(uuid.uuid4())
                        stru_dir_remote = f"{work_dir}/user_trajectories/{stru_id}"
                        remote_host = self.jf_config['workers'].get(effective_worker_name, {}).get('host', '')

                        try:
                            with tempfile.TemporaryDirectory() as tmpdir:
                                local_file = write_strus(software, strus_ase, tmpdir)
                                track_filename = os.path.basename(local_file)
                                traj_file_path = f"{stru_dir_remote}/{track_filename}"

                                subprocess.run(
                                    self._get_ssh_cmd(effective_worker_name, f'mkdir -p {stru_dir_remote}'),
                                    check=True, timeout=30,
                                )
                                subprocess.run(
                                    self._get_scp_cmd(effective_worker_name, local_file, traj_file_path),
                                    check=True, timeout=60,
                                )
                        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                            raise ConfigError(
                                f"Failed to upload trajectory to remote worker "
                                f"'{effective_worker_name}' (host={remote_host}). "
                                f"Check SSH connectivity and work_dir permissions. "
                                f"Target: {stru_dir_remote}"
                            ) from exc
                    else:
                        # Local worker: write directly to work_dir
                        stru_dir = Path(work_dir) / "user_trajectories" / str(uuid.uuid4())
                        stru_dir.mkdir(parents=True, exist_ok=True)
                        traj_file_path = write_strus(software, strus_ase, str(stru_dir))

                    traj_format = stru_format
                else:
                    raise ValidationError(
                        "SCF step requires NVE output. Include 'nve' in steps, "
                        "or set resume=True with a prev_task_id that has NVE results."
                    )

                nodes = (
                    input.scf_input.nodes
                    if input.scf_input.nodes is not None
                    else effective_worker_cfg['scf'][software]['nodes']
                )
                assert nodes > 0, "[SCF] nodes must be a positive integer or omitted to use the default."
                ntasks_per_node = effective_worker_cfg['scf'][software]['ntasks_per_node']
                cpus_per_task = effective_worker_cfg['scf'][software]['cpus_per_task']
                pp_path_raw = self._get_exec_config(
                    effective_worker_name, effective_worker_cfg, software, 'pp_path'
                )
                pp_path = str(Path(pp_path_raw).expanduser().resolve()) if pp_path_raw else ''
                orb_path = str(Path(effective_worker_cfg.get('orb_path', {}).get(software, '')).expanduser().resolve())

                jobs_scf = qdyn_scf(
                    software=software,
                    parameters=input.scf_input,
                    pp_path=pp_path,
                    orb_path=orb_path,
                    traj_file_path=traj_file_path,
                    traj_format=traj_format,
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
                            modules=self._get_exec_config(effective_worker_name, effective_worker_cfg, software, 'modules'),
                            export=self._get_exec_config(effective_worker_name, effective_worker_cfg, software, 'export'),
                            pre_run=self._get_exec_config(effective_worker_name, effective_worker_cfg, software, 'pre_run'),
                            post_run=None,
                        ),
                        resources={
                            **self._get_worker_resources(resource_worker),
                            'partition': self._get_machine_config(effective_worker_name, effective_worker_cfg)['partition'],
                            **effective_worker_cfg['scf'][software],
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

            machine_cfg = self._get_machine_config(effective_worker_name, effective_worker_cfg)
            ncpus = machine_cfg['cpus_per_node']
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
                    modules=self._get_exec_config(effective_worker_name, effective_worker_cfg, 'python', 'modules'),
                    export={
                        **self._get_exec_config(effective_worker_name, effective_worker_cfg, 'python', 'export'),
                        'OMP_NUM_THREADS': '4'
                    },
                    pre_run=self._get_exec_config(effective_worker_name, effective_worker_cfg, 'python', 'pre_run'),
                    post_run=None,
                ),
                resources={
                    **self._get_worker_resources(resource_worker),
                    'partition': machine_cfg['partition'],
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

            machine_cfg = self._get_machine_config(effective_worker_name, effective_worker_cfg)
            if input.namd_input.surface_hopping == 'FSSH':
                nodes = 1
                ntasks_per_node = 1
                cpus_per_task = machine_cfg['cpus_per_node']
            else:
                nodes = (
                    input.namd_input.nodes if input.namd_input.nodes is not None else 1
                )
                assert nodes > 0, "[NAMD] nodes must be a positive integer or omitted to use the default."
                ntasks_per_node = machine_cfg['cpus_per_node']
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
                    modules=self._get_exec_config(effective_worker_name, effective_worker_cfg, 'namd', 'modules'),
                    export={
                        **self._get_exec_config(effective_worker_name, effective_worker_cfg, 'namd', 'export'),
                        'OMP_NUM_THREADS': str(cpus_per_task),
                    },
                    pre_run=self._get_exec_config(effective_worker_name, effective_worker_cfg, 'namd', 'pre_run'),
                    post_run=None,
                ),
                resources={
                    **self._get_worker_resources(resource_worker),
                    'partition': machine_cfg['partition'],
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
        stru: str = '',
        stru_format: str = 'vasp',
        stru_hash: str = '',
        resume: bool = False,
        prev_task_id: str = '',
        *,
        task_id: str | None = None,
        username: str | None = None,
        pool_name: str | None = None,
        runtime_worker: str | None = None,
    ) -> Tuple[str, Dict[str, List[str]], str]:
        """Submit a workflow to jobflow-remote.

        Parameters
        ----------
        task_id : str, optional
            Pre-generated task ID (``suid()``).  When provided, the Flow
            is created with ``Flow(uuid=task_id)`` so the ID is stable
            across queue → dispatch transitions.  If None, the Flow
            auto-generates its own UUID.
        username : str, optional
            Authenticated user who submitted the task.  Written into
            Flow/Job metadata as ``qdyn_user``.
        pool_name : str, optional
            Logical pool name (e.g. ``local_slurm``).  Used for config
            lookup and metadata.
        runtime_worker : str, optional
            Actual jf-remote worker name (e.g. ``local_slurm_007``)
            selected at dispatch time.  Passed to ``submit_flow()`` and
            used for resource lookups.
        """
        self._ensure_job_controller()

        # Resolve pool context.
        effective_pool = pool_name
        effective_worker_name, effective_worker_cfg = self._resolve_worker_context(
            effective_pool
        )

        # Determine the worker name passed to submit_flow().
        submit_worker = runtime_worker or effective_worker_name

        jobs = self.main_workflow(
            input=input,
            method=method,
            stru=stru,
            stru_format=stru_format,
            stru_hash=stru_hash,
            resume=resume,
            prev_task_id=prev_task_id,
            worker_name=effective_worker_name,
            worker_cfg=effective_worker_cfg,
            runtime_worker=runtime_worker,
        )
        jobs_flatten = []
        for job_list in jobs.values():
            jobs_flatten.extend(job_list)

        # Build metadata dict for traceability and per-user queries.
        qdyn_metadata: Dict[str, Any] = {}
        if username:
            qdyn_metadata["qdyn_user"] = username
        if task_id:
            qdyn_metadata["qdyn_task_id"] = task_id
        if pool_name:
            qdyn_metadata["qdyn_pool"] = pool_name
        if runtime_worker:
            qdyn_metadata["qdyn_runtime_worker"] = runtime_worker

        # Create Flow with optional pre-generated UUID and metadata.
        flow_kwargs: Dict[str, Any] = {}
        if task_id:
            flow_kwargs["uuid"] = task_id
        if qdyn_metadata:
            flow_kwargs["metadata"] = qdyn_metadata
        flow = Flow(jobs_flatten, **flow_kwargs)

        # Propagate metadata to dynamically generated jobs as well.
        if qdyn_metadata:
            flow.update_metadata(qdyn_metadata, dynamic=True)

        submit_flow(flow, worker=submit_worker)

        final_task_id = flow.uuid
        job_ids: Dict[str, List[str]] = {}
        for key, value in jobs.items():
            job_ids[key] = [v.uuid for v in value]
        self.job_ids[final_task_id] = job_ids

        self.task_ids.append(final_task_id)

        return final_task_id, job_ids, submit_worker


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
        return self.get_job_info(job_uuid).state.value

    def get_job_info(self, job_uuid: str):
        """Query full job info object."""
        jc = self._ensure_job_controller()
        try:
            job_info = jc.get_job_info(job_id=job_uuid)
            assert job_info is not None
        except:
            raise QueryError(f"Job '{job_uuid}' not found.")
        return job_info


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

    def continue_task_jobs(self, task_id: str) -> Dict[str, List[str] | List[Dict[str, str]]]:
        """
        Resume all paused/stopped jobs for a task via flow-level resume.

        Returns a dictionary with keys: 'continued', 'skipped', 'failed'
        where each key maps to a list of job UUIDs or failed job info.
        """
        _RESUMABLE_STATES = {"PAUSED", "STOPPED", "USER_STOPPED"}

        job_ids = self.list_task_jobs(task_id)
        jc = self._ensure_job_controller()

        resumable: List[str] = []
        skipped: List[str] = []
        failed: List[Dict[str, str]] = []

        # Flatten all job UUIDs
        jobs_flatten: list[str] = []
        for job_list in job_ids.values():
            jobs_flatten.extend(job_list)

        # First scan: classify jobs
        for job_uuid in jobs_flatten:
            try:
                job_info = jc.get_job_info(job_id=job_uuid)
                if job_info is None:
                    skipped.append(job_uuid)
                    continue
                raw_state = job_info.state.value
            except Exception as exc:
                failed.append({"uuid": job_uuid, "error": f"Query failed: {exc}"})
                continue

            if raw_state in _RESUMABLE_STATES:
                resumable.append(job_uuid)
            else:
                skipped.append(job_uuid)

        if not resumable:
            return {"continued": [], "skipped": skipped, "failed": failed}

        # Verify flow exists
        flow_doc = jc.get_flow_info_by_flow_uuid(task_id)
        if flow_doc is None:
            raise QueryError(f"Flow '{task_id}' not found.")

        # Resume the entire flow
        try:
            jc.resume_flow(flow_id=task_id)
        except Exception as exc:
            raise QueryError(f"Failed to resume flow '{task_id}': {exc}")

        # Second scan: verify results
        continued: List[str] = []
        for job_uuid in resumable:
            try:
                job_info = jc.get_job_info(job_id=job_uuid)
                if job_info is None:
                    failed.append({"uuid": job_uuid, "error": "Job not found after resume"})
                    continue
                new_state = job_info.state.value
                if new_state in _RESUMABLE_STATES:
                    failed.append({"uuid": job_uuid, "error": f"Still in {new_state} after resume"})
                else:
                    continued.append(job_uuid)
            except Exception as exc:
                failed.append({"uuid": job_uuid, "error": f"Post-resume query failed: {exc}"})

        return {"continued": continued, "skipped": skipped, "failed": failed}

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
