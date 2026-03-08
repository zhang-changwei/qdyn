import asyncio
import shutil
from pathlib import Path
import requests
import logging
import io
import os
import yaml
from typing import Optional, Dict

from ase import Atoms
import ase.io
from jobflow_remote import set_run_config, submit_flow
from jobflow_remote.config.base import ExecutionConfig

from .input import InputT
from .tools.nvt import run_nvt


class MainWorkflow:

    def __init__(self, config_path: Optional[str] = None):
        self.config = self._load_config(config_path)

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
        stru: str,
        stru_format: str = 'vasp',
    ):
        # basic keys
        software = input.basic_input.software
        structure = ase.io.read(io.StringIO(stru), format=stru_format)
        
        jobs = []
        
        # step 1: NVT
        if 'NVT' in input.steps:
            nodes = self.config['nvt'][software]['nodes']
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
                }
            )

            jobs.append(job_nvt)

        job_ids = submit_flow(
            jobs, 
            worker = 'local_slurm',
        )
