import asyncio
from copy import deepcopy
import shutil
from pathlib import Path
import requests
import logging
import io
import os
import subprocess
import uuid
import yaml
from typing import Optional, Tuple, Dict, List, Literal

from ase import Atoms
import ase.io
from jobflow.core.job import Job
from jobflow.core.flow import Flow
from jobflow_remote import set_run_config, submit_flow
from jobflow_remote.config.base import ExecutionConfig
from jobflow_remote import get_jobstore

from .input import InputT
from .tools.nvt import run_nvt
from .tools.prepare_namd import run_pre_namd


class ValidationError(Exception):
    pass


class MainWorkflow:

    def __init__(self, config_path: Optional[str] = None):
        self.config = self._load_config(config_path)
        self.task_ids: List[str] = []
        # {'task_id': {'step': [job_uuid1, job_uuid2, ...]}}
        self.job_ids: Dict[str, Dict[str, List[str]]] = {}

        self.js = get_jobstore()
        self.js.connect()

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    @staticmethod
    def _load_config(config_path: Optional[str]) -> Dict:
        path = config_path or os.environ.get('QDYN_CONFIG') or 'config/qdyn.yaml'
        path = os.path.abspath(path)
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"QDYN config file not found: {path}\n"
                f"Create config/qdyn.yaml or set the QDYN_CONFIG environment variable."
            )
        with open(path) as f:
            cfg = yaml.safe_load(f)
        logging.info(f"Loaded config from {path}.")
        return cfg

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
    ) -> Tuple[str, Dict[str, List[Job | Flow]]]:

        # basic keys
        software = input.basic_input.software
        first_step = input.steps[0]
        flag = ''
        # resume
        if resume:
            assert prev_task_id, "prev_job_id must be provided when resume=True."

        task_id = str(uuid.uuid4())
        jobs: Dict[str, List[Job | Flow]] = {}

        # validate steps
        def is_continuous_steps(steps: List[int]) -> bool:
            if len(steps) <= 1:
                return True
            for i in range(1, len(steps)):
                if steps[i] != steps[i - 1] + 1:
                    return False
            return True

        if method == 'namd':
            key_map = {'nvt': 0, 'nve': 1, 'scf': 2, 'pre_namd': 3, 'namd': 4}
            try:
                step_int = [key_map[step] for step in input.steps]
                if not is_continuous_steps(sorted(step_int)):
                    raise ValidationError
            except:
                raise ValidationError(
                    f"Invalid steps for method {method}. Steps must be continuous and in the order of nvt -> nve -> scf -> pre_namd -> namd. Got {input.steps}."
                )
        else:
            raise NotImplementedError(f"Method {method} is not supported yet.")

        # step 1: NVT
        if 'nvt' in input.steps or flag == 'gen_input_nvt':
            prev_step = ''
            next_step = 'nve'
            if prev_step in input.steps:
                structure = jobs[prev_step][0].output['stru']
            elif first_step == 'nvt' and resume:
                prev_job_uuid = self.job_ids[prev_task_id][prev_step][0]
                structure = self.js.get_output(prev_job_uuid)['stru']  # type: ignore
            elif stru:
                structure = ase.io.read(io.StringIO(stru), format=stru_format)
            else:
                raise ValidationError(
                    "No structure provided for the first step. Provide a structure string or set resume=True with a valid prev_job_uuid."
                )

            nodes = (
                input.nvt_input.nodes
                if input.nvt_input.nodes is not None
                else self.config['nvt'][software]['nodes']
            )
            ntasks_per_node = self.config['nvt'][software]['ntasks_per_node']
            cpus_per_task = self.config['nvt'][software]['cpus_per_task']

            job_nvt = run_nvt(
                software=software,
                parameters=input.nvt_input,
                pp_path=self.config['pp_path'][software],
                orb_path=self.config['orb_path'][software],
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
                    modules=self.config['module'][software],
                    export=self.config['export'][software],
                    pre_run=None,
                    post_run=None,
                ),
                resources={
                    'nodes': nodes,
                    'ntasks_per_node': ntasks_per_node,
                    'cpus_per_task': cpus_per_task,
                },
            )
            jobs['nvt'] = [job_nvt]

            # update flag
            is_last_step = True if next_step not in input.steps else False
            if is_last_step:
                flag = f'gen_input_{next_step}'

        # step 2: NVE
        if 'nve' in input.steps or flag == 'gen_input_nve':
            prev_step = 'nvt'
            next_step = 'scf'
            if prev_step in input.steps:
                structure = jobs[prev_step][0].output['stru']
            elif first_step == 'nve' and resume:
                prev_job_uuid = self.job_ids[prev_task_id][prev_step][0]
                structure = self.js.get_output()['stru']  # type: ignore
            elif stru:
                structure = ase.io.read(io.StringIO(stru), format=stru_format)
            else:
                raise ValidationError(
                    "No structure provided for the first step. Provide a structure string or set resume=True with a valid prev_job_uuid."
                )

            nodes = (
                input.nve_input.nodes
                if input.nve_input.nodes is not None
                else self.config['nve'][software]['nodes']
            )
            ntasks_per_node = self.config['nve'][software]['ntasks_per_node']
            cpus_per_task = self.config['nve'][software]['cpus_per_task']

            job_nve = run_nve(
                software=software,
                parameters=input.nve_input,
                pp_path=self.config['pp_path'][software],
                orb_path=self.config['orb_path'][software],
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
                    modules=self.config['module'][software],
                    export=self.config['export'][software],
                    pre_run=None,
                    post_run=None,
                ),
                resources={
                    'nodes': nodes,
                    'ntasks_per_node': ntasks_per_node,
                    'cpus_per_task': cpus_per_task,
                },
            )
            jobs['nve'] = [job_nve]

            # update flag
            is_last_step = True if next_step not in input.steps else False
            if is_last_step:
                flag = f'gen_input_{next_step}'

        # step 3: SCF
        if 'scf' in input.steps or flag == 'gen_input_scf':
            if software == 'abacus':
                # no need for scf calc if using abacus
                pass
            else:
                prev_step = 'nve'
                next_step = 'pre_namd'
                if prev_step in input.steps:
                    structures = jobs[prev_step][0].output['strus']
                elif first_step == 'scf' and resume:
                    prev_job_uuid = self.job_ids[prev_task_id][prev_step][0]
                    structures = self.js.get_output(prev_job_uuid)['strus']  # type: ignore
                else:
                    raise ValidationError()

                nodes = (
                    input.scf_input.nodes
                    if input.scf_input.nodes is not None
                    else self.config['scf'][software]['nodes']
                )
                ntasks_per_node = self.config['scf'][software]['ntasks_per_node']
                cpus_per_task = self.config['scf'][software]['cpus_per_task']

                jobs_scf = run_scf(
                    software=software,
                    parameters=input.scf_input,
                    pp_path=self.config['pp_path'][software],
                    orb_path=self.config['orb_path'][software],
                    structures=structures,
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
                            modules=self.config['module'][software],
                            export=self.config['export'][software],
                            pre_run=None,
                            post_run=None,
                        ),
                        resources={
                            'nodes': nodes,
                            'ntasks_per_node': ntasks_per_node,
                            'cpus_per_task': cpus_per_task,
                        },
                    )
                jobs['scf'] = jobs_scf

                # update flag
                is_last_step = True if next_step not in input.steps else False
                if is_last_step:
                    flag = f'gen_input_{next_step}'

        # step 4: PRE_NAMD
        if 'pre_namd' in input.steps or flag == 'gen_input_pre_namd':
            prev_step = 'scf' if software != 'abacus' else 'nve'
            next_step = 'namd'
            if prev_step in input.steps:
                run_dirs = [
                    jobs[prev_step][idx].output['run_dir'] 
                    for idx in range(len(jobs[prev_step]))
                ]
                prev_output = jobs[prev_step][0].output
            elif first_step == 'pre_namd' and resume:
                prev_jobs = self.job_ids[prev_task_id][prev_step]
                run_dirs = [self.js.get_output(prev_job_uuid)['run_dir'] for prev_job_uuid in prev_jobs]  # type: ignore
                prev_output = self.js.get_output(prev_jobs[0])
            else:
                raise ValidationError()

            ncpus = self.config['machine']['cpus_per_node']
            job_pre_namd = run_pre_namd(
                software=software,
                parameters=input.prenamd_input,
                run_dirs=run_dirs,
                prev_output=prev_output,
                nproc=ncpus // 4,
                plot=input.basic_input.plot,
                prepare_input_only=bool(flag),
            )
            job_pre_namd = set_run_config(
                job_pre_namd,
                exec_config=ExecutionConfig(
                    modules=self.config['module']['python'],
                    export={**self.config['export']['python'], 
                            'OMP_NUM_THREADS': '4'},
                    pre_run=None,
                    post_run=None,
                ),
                resources={
                    'nodes': 1,
                    'ntasks_per_node': 1,
                    'cpus_per_task': ncpus,
                },
            )
            jobs['pre_namd'] = [job_pre_namd]

            # update flag
            is_last_step = True if next_step not in input.steps else False
            if is_last_step:
                flag = f'gen_input_{next_step}'

        return task_id, jobs

    def submit(
        self,
        input: InputT,
        method: Literal['namd', 'n2amd'] = 'namd',
        stru: Optional[str] = '',
        stru_format: str = 'vasp',
        resume: bool = False,
        prev_task_id: str = '',
    ) -> str:

        task_id, jobs = self.main_workflow(
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
        db_ids = submit_flow(
            jobs_flatten,
            worker='local_slurm',
        )

        job_ids = {}
        for key, value in jobs.items():
            job_ids[key] = [v.uuid for v in value]
        self.job_ids[task_id] = job_ids

        self.task_ids.append(task_id)

        return task_id

    def remove_task(self, task_id: str):
        pass

    def list_tasks(self) -> List[str]:
        return self.task_ids

    def list_jobs(self, task_id: str):
        pass

    def get_jobs_status(self, job_uuid: List[str]):
        pass

    def get_job_output(self, job_uuid: str):
        pass
