import json
from pathlib import Path
import logging
import io
import os
import sqlite3
from typing import Any, Tuple, Dict, List, Literal, Sequence

from ase import Atoms
from jobflow.core.job import Job
from jobflow.core.flow import Flow
from jobflow_remote import SETTINGS, set_run_config, submit_flow
from jobflow_remote.config.base import ExecutionConfig
from jobflow_remote import JobController

from .errors import ConfigError, ResumeError, ValidationError, QueryError
from .input import (
    DFTBaseInputT, InputT,
    NVTInputT, NVEInputT, SCFInputT, PreNAMDInputT, NAMDInputT,
)
from .resources import build_qresources
from .validation import load_config, validate_workflow_input
from .calc_common import TRAJ_FORMAT_MAPPING, read_stru
from .pool import WorkerPool

from .tools.nvt import qdyn_nvt
from .tools.nve import qdyn_nve
from .tools.scf import qdyn_scf
from .tools.fused_scf_prenamd import qdyn_fused_scf_prenamd
from .tools.prepare_namd import qdyn_pre_namd
from .tools.namd import qdyn_namd
from .ml_tools.mlff_wrapper import resolve_model_path


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

    def __init__(self, config_path: str | Path):
        self.config, self.jf_config = load_config(config_path)
        self.task_ids: List[str] = []
        # {'task_id': {'step': [job_uuid1, job_uuid2, ...]}}
        self.job_ids: Dict[str, Dict[str, List[str]]] = {}
        self.jc: JobController | None = None
        

    def __del__(self):
        jc = getattr(self, "jc", None)
        if jc is not None:
            jc.close()

    # ------------------------------------------------------------------
    # Pool helpers
    # ------------------------------------------------------------------

    def init_active_pool(self) -> None:
        self.active_pool = self.get_pool(self.config["active_pool"])

    def switch_active_pool(self, pool_name: str) -> None:
        raise NotImplementedError(
            "Switching active pool is not implemented yet."
        )

    def get_pool(self, pool_name: str) -> WorkerPool:
        """Return a pool object by name, caching non-active pools lazily."""
        active_pool = getattr(self, "active_pool", None)
        if active_pool is not None and pool_name == active_pool.name:
            return active_pool

        cache = getattr(self, "_pool_cache", None)
        if cache is None:
            cache = {}
            self._pool_cache = cache
        if pool_name not in cache:
            cache[pool_name] = WorkerPool(
                job_controller=self._ensure_job_controller(),
                pool_name=pool_name,
                config=self.config,
                jf_config=self.jf_config,
            )
        return cache[pool_name]

    def get_task_pool_name(self, task_id: str) -> str:
        """Resolve the pool that owns an existing task."""
        from .database import qdyndb

        meta = qdyndb.get_task_metadata(task_id) or {}
        pool_name = meta.get("pool_name")
        if pool_name:
            return pool_name

        queued = qdyndb.get_queued_status(task_id)
        if queued and queued.get("pool_name"):
            return queued["pool_name"]

        raise QueryError(f"Pool for task '{task_id}' not found.")

    def get_task_pool(self, task_id: str) -> WorkerPool:
        """Return the pool associated with a task."""
        return self.get_pool(self.get_task_pool_name(task_id))

    def _resolve_pool_context(
        self, pool_name_override: str | None = None
    ) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
        """Resolve pool name, worker config, and pool parameters.

        Returns (pool_name_override, worker_cfg, pool_config).
        """
        name = pool_name_override or self.active_pool.name
        if name not in self.config['worker_pools']:
            raise ValidationError(
                f"Pool '{name}' not found in config. "
                f"Available: {list(self.config['worker_pools'].keys())}"
            )
        pool_def = self.config['worker_pools'][name]
        return name, pool_def['worker'], pool_def['pool']

    def _ensure_job_controller(self) -> JobController:
        """Initialize the jobflow-remote controller on demand."""

        def _configure_jobflow_remote() -> None:
            """Apply optional jobflow-remote settings from qdyn.yaml before first use."""
            project_path = self.config["basic"]["jf_project_path"]
            project_name = self.config["basic"]["jf_project_name"]

            SETTINGS.projects_folder = str(Path(project_path).parent.expanduser().resolve())
            SETTINGS.project = project_name

        if self.jc is None:
            try:
                _configure_jobflow_remote()
                self.jc = JobController.from_project_name()
            except Exception as exc:
                raise ConfigError(
                    "Failed to initialize jobflow-remote.\n"
                    "Set basic.jf_project_path/jf_project_name in qdyn.yaml "
                ) from exc
        return self.jc

    # ------------------------------------------------------------------
    # Worker-aware helpers
    # ------------------------------------------------------------------

    def _get_exec_config(self, software: str, key: str):
        """Get execution config for the active pool and software."""
        return self.active_pool.worker_cfg[key][software]

    def _get_first_step(
        self, steps: Sequence[str], method: Literal['namd', 'n2amd']
    ) -> str:
        if method != 'namd':
            raise NotImplementedError(f"Method '{method}' is not supported yet.")
        key_map = {
            'nvt': 0,
            'nve': 1,
            'scf': 2,
            'fused_scf_prenamd': 2,
            'pre_namd': 3,
            'namd': 4,
        }
        return min(steps, key=lambda step: key_map[step])

    @staticmethod
    def _should_run_step(step: str, steps: Sequence[str], flag: str) -> bool:
        return step in steps or flag == f'gen_input_{step}'

    @staticmethod
    def _advance_prepare_flag(
        flag: str, steps: Sequence[str], current_step: str, next_step: str
    ) -> str:
        if next_step and current_step in steps and next_step not in steps:
            return f'gen_input_{next_step}'
        return flag

    def _build_exec_config(
        self,
        software_names: list[str],
        *,
        omp_threads: int | None = None,
    ) -> ExecutionConfig:
        modules: list[str] = []
        export: dict[str, Any] = {}
        pre_run_parts: list[str] = []

        for software_name in software_names:
            modules.extend(
                self._get_exec_config(software_name, 'modules')
            )
            export.update(
                self._get_exec_config(software_name, 'export')
            )
            pre_run = self._get_exec_config(
                software_name, 'pre_run'
            )
            if pre_run:
                pre_run_parts.append(pre_run)

        if omp_threads is not None:
            export['OMP_NUM_THREADS'] = str(omp_threads)
            export['MKL_NUM_THREADS'] = str(omp_threads)

        return ExecutionConfig(
            modules=list(dict.fromkeys(modules)),
            export=export,
            pre_run='\n'.join(pre_run_parts),
            post_run=None,
        )

    def step_nvt(
        self,
        *,
        input: NVTInputT,
        jobs: Dict[str, List[Job | Flow]],
        is_first_step: bool,
        stru: str,
        stru_format: str,
        resume: bool,
        prev_task_id: str,
        prepare_input_only: bool,
        plot: bool,
    ) -> list[Job | Flow]:
        active_worker_cfg = self.active_pool.worker_cfg
        software = input.software
        if is_first_step and resume:
            try:
                prev_job_uuid = self.job_ids[prev_task_id]['nvt'][0]
                structure = self.get_job_output(prev_job_uuid)['stru']
            except Exception as exc:
                raise ResumeError(
                    "Previous job for step 'nvt' not found or has no output. "
                    "Cannot resume nvt."
                ) from exc
        elif stru:
            with io.StringIO(stru) as s:
                structure = read_stru(stru_format, s).todict()
            if structure.get('constraints') is not None:
                structure['constraints'] = [i.todict() for i in structure['constraints']]  # type: ignore[index]
        else:
            raise ValidationError(
                "No structure provided for the nvt step. \n"
                "Provide a structure string or set resume=True with a valid prev_task_id."
            )
        
        calculator = input.calculator

        if isinstance(calculator, DFTBaseInputT):
            nodes = (
                calculator.nodes
                if  calculator.nodes is not None
                else active_worker_cfg['nvt'][software]['nodes']
            )
            processes_per_node = active_worker_cfg['nvt'][software]['processes_per_node']
            threads_per_process = active_worker_cfg['nvt'][software]['threads_per_process']
            pp_path = active_worker_cfg["pp_path"][software]
            orb_path = active_worker_cfg["orb_path"][software]
            model_path = ''
            res_software = software
            use_gpu = False
        else:
            nodes = 1
            processes_per_node = 1
            threads_per_process = active_worker_cfg['cpus_per_node']
            pp_path = ''
            orb_path = ''
            model_path = resolve_model_path(self.active_pool, calculator)
            res_software = 'python'
            use_gpu = calculator.use_gpu

        job_nvt = qdyn_nvt(
            software=software,
            parameters=input,
            pp_path=pp_path,
            orb_path=orb_path,
            structure=structure,
            model_path=model_path,
            nodes=nodes,
            processes_per_node=processes_per_node,
            threads_per_process=threads_per_process,
            plot=plot,
            prepare_input_only=prepare_input_only,
        )
        qres = build_qresources(
            active_worker_cfg,
            use_gpu=use_gpu,
            nodes=nodes,
            processes_per_node=processes_per_node,
            threads_per_process=threads_per_process,
        )
        job_nvt = set_run_config(
            job_nvt,
            exec_config=self._build_exec_config(
                [res_software],
                omp_threads=qres.threads_per_process,
            ),
            resources=qres,
        )
        return [job_nvt]

    def step_nve(
        self,
        *,
        input: NVEInputT,
        jobs: Dict[str, List[Job | Flow]],
        is_first_step: bool,
        stru: str,
        stru_format: str,
        resume: bool,
        prev_task_id: str,
        prepare_input_only: bool,
        plot: bool,
    ) -> list[Job | Flow]:
        active_worker_cfg = self.active_pool.worker_cfg
        software = input.software
        if 'nvt' in jobs:
            structure = jobs['nvt'][0].output['stru']
        elif is_first_step and resume:
            try:
                prev_job_uuid = self.job_ids[prev_task_id]['nvt'][0]
                structure = self.get_job_output(prev_job_uuid)['stru']
            except Exception as exc:
                raise ResumeError(
                    "Previous job for step 'nvt' not found or has no output. "
                    "Cannot resume nve."
                ) from exc
        elif stru:
            with io.StringIO(stru) as s:
                structure = read_stru(stru_format, s).todict()
            if structure.get('constraints') is not None:
                structure['constraints'] = [i.todict() for i in structure['constraints']]  # type: ignore[index]
        else:
            raise ValidationError(
                "No structure provided for NVE step. \n"
                "Provide a structure string or set resume=True with a valid prev_task_id."
            )

        calculator = input.calculator
        
        if isinstance(calculator, DFTBaseInputT):
            nodes = (
                calculator.nodes
                if  calculator.nodes is not None
                else active_worker_cfg['nve'][software]['nodes']
            )
            processes_per_node = active_worker_cfg['nve'][software]['processes_per_node']
            threads_per_process = active_worker_cfg['nve'][software]['threads_per_process']
            pp_path = active_worker_cfg["pp_path"][software]
            orb_path = active_worker_cfg["orb_path"][software]
            model_path = ''
            res_software = software
            use_gpu = False
        else:
            nodes = 1
            processes_per_node = 1
            threads_per_process = active_worker_cfg['cpus_per_node']
            pp_path = ''
            orb_path = ''
            model_path = resolve_model_path(self.active_pool, calculator)
            res_software = 'python'
            use_gpu = calculator.use_gpu

        job_nve = qdyn_nve(
            software=software,
            parameters=input,
            pp_path=pp_path,
            orb_path=orb_path,
            structure=structure,
            model_path=model_path,
            nodes=nodes,
            processes_per_node=processes_per_node,
            threads_per_process=threads_per_process,
            plot=plot,
            prepare_input_only=prepare_input_only,
        )
        qres = build_qresources(
            active_worker_cfg,
            use_gpu=use_gpu,
            nodes=nodes,
            processes_per_node=processes_per_node,
            threads_per_process=threads_per_process,
        )
        job_nve = set_run_config(
            job_nve,
            exec_config=self._build_exec_config(
                [res_software], 
                omp_threads=qres.threads_per_process
            ),
            resources=qres,
        )
        return [job_nve]

    def step_scf(
        self,
        *,
        input: SCFInputT,
        jobs: Dict[str, List[Job | Flow]],
        is_first_step: bool,
        stru_format: str,
        stru_hash: str,
        resume: bool,
        prev_task_id: str,
        prepare_input_only: bool,
        plot: bool,
    ) -> list[Job | Flow]:
        active_worker_cfg = self.active_pool.worker_cfg
        software = input.software

        if 'nve' in jobs:
            nve_output = jobs['nve'][0].output
            traj_path = nve_output['traj_path']
            traj_format = TRAJ_FORMAT_MAPPING[nve_output['software']] # type: ignore[index]
        elif is_first_step and resume:
            try:
                prev_job_uuid = self.job_ids[prev_task_id]['nve'][0]
                nve_output = self.get_job_output(prev_job_uuid)
                traj_path = nve_output['traj_path']
                traj_format = TRAJ_FORMAT_MAPPING[nve_output['software']]
            except Exception as exc:
                raise ResumeError(
                    "Previous job for step 'nve' not found or has no output. "
                    "Cannot resume scf."
                ) from exc
        elif stru_hash:
            traj_path = self.active_pool.get_user_file_path(
                file_type="trajectory",
                file_hash=stru_hash,
            )
            traj_format = stru_format
        else:
            raise ValidationError(
                "SCF step requires NVE output. Include 'nve' in steps, "
                "or set resume=True with a prev_task_id that has NVE results."
            )
        
        calculator = input.calculator

        if isinstance(calculator, DFTBaseInputT):
            nodes = (
                calculator.nodes
                if calculator.nodes is not None
                else active_worker_cfg['scf'][software]['nodes']
            )
            processes_per_node = active_worker_cfg['scf'][software]['processes_per_node']
            threads_per_process = active_worker_cfg['scf'][software]['threads_per_process']
            pp_path = active_worker_cfg["pp_path"][software]
            orb_path = active_worker_cfg["orb_path"][software]
            model_path = ''
            res_software = software
            use_gpu = False
        else:
            nodes = 1
            ncpus = active_worker_cfg['cpus_per_node']
            processes_per_node = min(8, ncpus)
            threads_per_process = max(1, ncpus // processes_per_node)
            pp_path = ''
            orb_path = ''
            model_path = resolve_model_path(self.active_pool, calculator)
            res_software = calculator.ham_type
            use_gpu = False # calculator.use_gpu

        jobs_scf = qdyn_scf(
            software=software,
            parameters=input,
            pp_path=pp_path,
            orb_path=orb_path,
            traj_path=traj_path, # type: ignore
            traj_format=traj_format,
            model_path=model_path,
            nodes=nodes,
            processes_per_node=processes_per_node,
            threads_per_process=threads_per_process,
            plot=plot,
            prepare_input_only=prepare_input_only,
        )
        qres = build_qresources(
            active_worker_cfg,
            use_gpu=use_gpu,
            nodes=nodes,
            processes_per_node=processes_per_node,
            threads_per_process=threads_per_process,
        )
        jobs_scf = [
            set_run_config(
                job_scf,
                exec_config=self._build_exec_config(
                    [res_software],
                    omp_threads=qres.threads_per_process,
                ),
                resources=qres,
            ) for job_scf in jobs_scf
        ]

        return jobs_scf

    def step_fused_scf_prenamd(
        self,
        *,
        scf_input: SCFInputT,
        prenamd_input: PreNAMDInputT,
        jobs: Dict[str, List[Job | Flow]],
        is_first_step: bool,
        stru_format: str,
        stru_hash: str,
        resume: bool,
        prev_task_id: str,
        prepare_input_only: bool,
        plot: bool,
    ) -> list[Job | Flow]:
        active_worker_cfg = self.active_pool.worker_cfg
        software = scf_input.software

        if 'nve' in jobs:
            nve_output = jobs['nve'][0].output
            traj_path = nve_output['traj_path']
            traj_format = TRAJ_FORMAT_MAPPING[nve_output['software']] # type: ignore[index]
        elif is_first_step and resume:
            try:
                prev_job_uuid = self.job_ids[prev_task_id]['nve'][0]
                nve_output = self.get_job_output(prev_job_uuid)
                traj_path = nve_output['traj_path']
                traj_format = TRAJ_FORMAT_MAPPING[nve_output['software']]
            except Exception as exc:
                raise ResumeError(
                    "Previous job for step 'nve' not found or has no output. "
                    "Cannot resume fused_scf_prenamd."
                ) from exc
        elif stru_hash:
            traj_path = self.active_pool.get_user_file_path(
                file_type="trajectory",
                file_hash=stru_hash,
            )
            traj_format = stru_format
        else:
            raise ValidationError(
                "FUSED_SCF_PRENAMD step requires NVE output. Include 'nve' in steps, "
                "or set resume=True with a prev_task_id that has NVE results."
            )
        
        calculator = scf_input.calculator

        if isinstance(calculator, DFTBaseInputT):
            nodes = (
                calculator.nodes
                if calculator.nodes is not None
                else active_worker_cfg['scf'][software]['nodes']
            )
            processes_per_node = active_worker_cfg['scf'][software]['processes_per_node']
            threads_per_process = active_worker_cfg['scf'][software]['threads_per_process']
            ncpus = processes_per_node * threads_per_process
            pp_path = active_worker_cfg["pp_path"][software]
            orb_path = active_worker_cfg["orb_path"][software]
            model_path = ''
            res_software = software
            use_gpu = False
        else:
            nodes = 1
            ncpus = active_worker_cfg['cpus_per_node']
            processes_per_node = min(8, ncpus)
            threads_per_process = max(1, ncpus // processes_per_node)
            pp_path = ''
            orb_path = ''
            model_path = resolve_model_path(self.active_pool, calculator)
            res_software = calculator.ham_type
            use_gpu = False # calculator.use_gpu
        nprocs_dft = processes_per_node
        nprocs_py = max(1, min(8, ncpus))
        omp_py = max(1, ncpus // nprocs_py)

        jobs_fused = qdyn_fused_scf_prenamd(
            software=software,
            scf_input=scf_input,
            prenamd_input=prenamd_input,
            pp_path=pp_path,
            orb_path=orb_path,
            traj_path=traj_path, # type: ignore
            traj_format=traj_format,
            model_path=model_path,
            nodes=nodes,
            ncpus=ncpus,
            nprocs_dft=nprocs_dft,
            nprocs_py=nprocs_py,
            plot=plot,
            prepare_input_only=prepare_input_only,
        )

        qres = build_qresources(
            active_worker_cfg,
            use_gpu=use_gpu,
            nodes=nodes,
            processes_per_node=nprocs_py,
            threads_per_process=omp_py,
        )
        njobs = len(jobs_fused)
        jobs_fused = [
            set_run_config(
                job_fused,
                exec_config=self._build_exec_config(
                    software_names=(
                        ['python'] 
                        if idx == njobs - 1 
                        else [res_software]
                    ),
                    omp_threads=omp_py,
                ),
                resources=qres,
            ) for idx, job_fused in enumerate(jobs_fused)
        ]
        return jobs_fused

    def step_pre_namd(
        self,
        *,
        input: PreNAMDInputT,
        jobs: Dict[str, List[Job | Flow]],
        is_first_step: bool,
        resume: bool,
        prev_task_id: str,
        prepare_input_only: bool,
        plot: bool,
    ) -> list[Job | Flow]:
        active_worker_cfg = self.active_pool.worker_cfg
        prev_step = 'scf'
        if prev_step in jobs:
            run_dirs = [jobs[prev_step][idx].output['run_dir'] for idx in range(len(jobs[prev_step]))]
            software = jobs[prev_step][-1].output['software']
        elif is_first_step and resume:
            try:
                run_dirs = []
                software = ''
                for prev_job_uuid in self.job_ids[prev_task_id][prev_step]:
                    output = self.get_job_output(prev_job_uuid)
                    run_dirs.append(output['run_dir'])
                    software = output['software']
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

        ncpus = active_worker_cfg['cpus_per_node']
        omp_threads = max(1, min(4, ncpus))
        job_pre_namd = qdyn_pre_namd(
            software=software,
            parameters=input,
            run_dirs=run_dirs,
            nproc=max(1, ncpus // omp_threads),
            plot=plot,
            prepare_input_only=prepare_input_only,
        )
        job_pre_namd = set_run_config(
            job_pre_namd,
            exec_config=self._build_exec_config(
                ['python'],
                omp_threads=omp_threads,
            ),
            resources=build_qresources(
                active_worker_cfg,
                nodes=1,
                processes_per_node=1,
                threads_per_process=ncpus,
            ),
        )
        return [job_pre_namd]

    def step_namd(
        self,
        *,
        input: NAMDInputT,
        jobs: Dict[str, List[Job | Flow]],
        is_first_step: bool,
        resume: bool,
        prev_task_id: str,
        prepare_input_only: bool,
        plot: bool,
    ) -> list[Job | Flow]:
        active_worker_cfg = self.active_pool.worker_cfg
        if 'fused_scf_prenamd' in jobs:
            prev_output = jobs['fused_scf_prenamd'][-1].output
        elif 'pre_namd' in jobs:
            prev_output = jobs['pre_namd'][0].output
        elif is_first_step and resume:
            prev_step = (
                'fused_scf_prenamd'
                if 'fused_scf_prenamd' in self.job_ids.get(prev_task_id, {})
                else 'pre_namd'
            )
            try:
                prev_job_uuid = self.job_ids[prev_task_id][prev_step][-1]
                prev_output = self.get_job_output(prev_job_uuid)
            except Exception as exc:
                raise ResumeError(
                    f"Previous job for step '{prev_step}' not found or has no output. "
                    f"Cannot resume namd."
                ) from exc
        else:
            raise ValidationError(
                "NAMD step requires PRE_NAMD or FUSED_SCF_PRENAMD output. "
                "Include 'pre_namd'/'fused_scf_prenamd' in steps, or set "
                "resume=True with a prev_task_id that has those results."
            )

        if input.surface_hopping == 'FSSH':
            nodes = 1
            processes_per_node = 1
            threads_per_process = active_worker_cfg['cpus_per_node']
        else:
            nodes = (
                input.nodes
                if input.nodes is not None
                else 1
            )
            processes_per_node = active_worker_cfg['cpus_per_node']
            threads_per_process = 1

        job_namd = qdyn_namd(
            parameters=input,
            nac_path=prev_output['nac_path'],
            deph_path=prev_output['deph_path'],
            VBM=prev_output['VBM'],
            CBM=prev_output['CBM'],
            nodes=nodes,
            processes_per_node=processes_per_node,
            threads_per_process=threads_per_process,
            plot=plot,
            prepare_input_only=prepare_input_only,
        )
        job_namd = set_run_config(
            job_namd,
            exec_config=self._build_exec_config(
                ['namd'],
                omp_threads=threads_per_process,
            ),
            resources=build_qresources(
                active_worker_cfg,
                nodes=nodes,
                processes_per_node=processes_per_node,
                threads_per_process=threads_per_process,
            ),
        )
        return [job_namd]

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
    ) -> Dict[str, List[Job | Flow]]:
        '''
        Notice: assume the config is valid,
                no error handling for missing config entries.
        '''

        # basic keys
        jobs: Dict[str, List[Job | Flow]] = {}
        flag = ''
        active_pool = self.active_pool
        active_worker_cfg = active_pool.worker_cfg

        # pre-flight validation
        validate_workflow_input(
            input,
            method,
            stru,
            stru_format,
            stru_hash,
            resume,
            prev_task_id,
            known_task_ids=self.task_ids,
            config=self.config,
            worker_cfg=active_worker_cfg,
            active_pool=active_pool,
        )

        first_step = self._get_first_step(input.steps, method)

        if self._should_run_step('nvt', input.steps, flag) and input.nvt_input is not None:
            next_step = 'nve'
            jobs['nvt'] = self.step_nvt(
                input=input.nvt_input,
                jobs=jobs,
                is_first_step=first_step == 'nvt',
                stru=stru,
                stru_format=stru_format,
                resume=resume,
                prev_task_id=prev_task_id,
                prepare_input_only=bool(flag),
                plot=input.plot,
            )
            flag = self._advance_prepare_flag(flag, input.steps, 'nvt', next_step)

        if self._should_run_step('nve', input.steps, flag) and input.nve_input is not None:
            next_step = (
                'fused_scf_prenamd'
                if 'fused_scf_prenamd' in input.steps
                else 'scf'
            )
            jobs['nve'] = self.step_nve(
                input=input.nve_input,
                jobs=jobs,
                is_first_step=first_step == 'nve',
                stru=stru,
                stru_format=stru_format,
                resume=resume,
                prev_task_id=prev_task_id,
                prepare_input_only=bool(flag),
                plot=input.plot,
            )
            flag = self._advance_prepare_flag(flag, input.steps, 'nve', next_step)

        if self._should_run_step('scf', input.steps, flag) and input.scf_input is not None:
            next_step = 'pre_namd'
            jobs_scf = self.step_scf(
                input=input.scf_input,
                jobs=jobs,
                is_first_step=first_step == 'scf',
                stru_format=stru_format,
                stru_hash=stru_hash,
                resume=resume,
                prev_task_id=prev_task_id,
                prepare_input_only=bool(flag),
                plot=input.plot,
            )
            # ABACUS does not need a separate SCF job before PRE_NAMD, so
            # step_scf() returns an empty list and we should not register it.
            if jobs_scf:
                jobs['scf'] = jobs_scf
            flag = self._advance_prepare_flag(flag, input.steps, 'scf', next_step)

        if (
            self._should_run_step('fused_scf_prenamd', input.steps, flag)
            and input.scf_input is not None
            and input.prenamd_input is not None
        ):
            next_step = 'namd'
            jobs['fused_scf_prenamd'] = self.step_fused_scf_prenamd(
                scf_input=input.scf_input,
                prenamd_input=input.prenamd_input,
                jobs=jobs,
                is_first_step=first_step == 'fused_scf_prenamd',
                stru_format=stru_format,
                stru_hash=stru_hash,
                resume=resume,
                prev_task_id=prev_task_id,
                prepare_input_only=bool(flag),
                plot=input.plot,
            )
            flag = self._advance_prepare_flag(
                flag, input.steps, 'fused_scf_prenamd', next_step
            )

        if (
            self._should_run_step('pre_namd', input.steps, flag)
            and input.prenamd_input is not None
        ):
            next_step = 'namd'
            jobs['pre_namd'] = self.step_pre_namd(
                input=input.prenamd_input,
                jobs=jobs,
                is_first_step=first_step == 'pre_namd',
                resume=resume,
                prev_task_id=prev_task_id,
                prepare_input_only=bool(flag),
                plot=input.plot,
            )
            flag = self._advance_prepare_flag(flag, input.steps, 'pre_namd', next_step)

        if self._should_run_step('namd', input.steps, flag) and input.namd_input is not None:
            next_step = ''
            jobs['namd'] = self.step_namd(
                input=input.namd_input,
                jobs=jobs,
                is_first_step=first_step == 'namd',
                resume=resume,
                prev_task_id=prev_task_id,
                prepare_input_only=bool(flag),
                plot=input.plot,
            )
            flag = self._advance_prepare_flag(flag, input.steps, 'namd', next_step)

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
            Logical pool name. Must match the active pool.
        runtime_worker : str, optional
            Actual jf-remote worker name (e.g. ``local_slurm_007``)
            selected at dispatch time. Passed to ``submit_flow()``.
        """
        self._ensure_job_controller()

        active_pool = self.active_pool
        active_worker_name = active_pool.name
        if pool_name is not None and pool_name != active_pool.name:
            raise ValidationError(
                f"Task submission is restricted to the active pool '{active_pool.name}', "
                f"got '{pool_name}'."
            )
        pool_name = active_pool.name

        # Determine the worker name passed to submit_flow().
        submit_worker = runtime_worker or active_worker_name

        jobs = self.main_workflow(
            input=input,
            method=method,
            stru=stru,
            stru_format=stru_format,
            stru_hash=stru_hash,
            resume=resume,
            prev_task_id=prev_task_id,
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
            if job_info is None:
                raise
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

    def stop_task_jobs(
        self, task_id: str
    ) -> Dict[str, List[str] | List[Dict[str, str]]]:
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

        return {"stopped": stopped, "skipped": skipped, "failed": failed}

    def continue_task_jobs(
        self, task_id: str
    ) -> Dict[str, List[str] | List[Dict[str, str]]]:
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
                    failed.append(
                        {"uuid": job_uuid, "error": "Job not found after resume"}
                    )
                    continue
                new_state = job_info.state.value
                if new_state in _RESUMABLE_STATES:
                    failed.append(
                        {
                            "uuid": job_uuid,
                            "error": f"Still in {new_state} after resume",
                        }
                    )
                else:
                    continued.append(job_uuid)
            except Exception as exc:
                failed.append(
                    {"uuid": job_uuid, "error": f"Post-resume query failed: {exc}"}
                )

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
