import asyncio
import os
from os.path import join as pjoin
import shutil
import subprocess
import time
import uuid
import logging

from typing import Optional, List
from .constants import JOB_MANAGER_POLL_INTERVAL

class Job:

    def __init__(self, nodes: int, script_path: str, task: 'Task'):
        self.uuid = str(uuid.uuid4())
        self.job_id: int = 0
        self.status: str = 'waiting'
        self.nodes = nodes
        self.script_path = script_path
        self.retry: int = 0
        self.task: 'Task' = task

class Task:
    
    def __init__(self, quota: int):
        self.uuid = str(uuid.uuid4())
        self.quota: int = quota
        self.used: int = 0


class SlurmManager:

    def __init__(self):
        self.tasks = set()
        self.jobs: List[Job] = []

    async def poll(self) -> None:
        await asyncio.sleep(JOB_MANAGER_POLL_INTERVAL)
        self.check_job_status()
        self.submit_jobs()


    def submit_jobs(self) -> None:
        for job in self.jobs:
            if job.status == 'waiting' and job.task.used + job.nodes <= job.task.quota:
                # 提交任务
                result = subprocess.run(
                    ['sbatch', rf'{job.script_path}'], capture_output=True, text=True
                )

                if result.returncode != 0:
                    raise RuntimeError(f"Slurm submission failed: {result.stderr}")

                # 提取任务ID
                try:
                    job_id = result.stdout.split(';')[0]
                    job.job_id = int(job_id)
                    job.status = 'pending'
                    job.task.used += job.nodes
                except:
                    raise RuntimeError("Failed to extract Slurm job ID")


    def check_job_status(self) -> None:
        running_jobs = []
        job_ids = []
        for job in self.jobs:
            if job.status in ['pending', 'running']:
                running_jobs.append(job)
                job_ids.append(str(job.job_id))
        if job_ids:
            result = subprocess.run(
                ['sacct', '-j', ','.join(job_ids), '--format=JobID,State', '--noheader', '-X'],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                logging.warning(f"Failed to check job status: {result.stderr}")
                return
            
            lines = result.stdout.strip().split('\n')
            for line in lines:
                job_id, state = line.split()
                job_id = int(job_id)
                state = state.lower()
                
                for job in running_jobs:
                    if job.job_id == job_id:
                        job.state = state
                        if state not in ['pending', 'running']:
                            job.task.used -= job.nodes
                        break
    
    def add_task(self, quota: int) -> str:
        task = Task(quota=quota)
        self.tasks.add(task)
        return task.uuid

    def delete_task(self, task_id: str) -> None:
        pass

    def register_job(self, 
                     task_id: str,
                     dependency: str,
                     command: str,
                     working_dir: str,
                     partition: str,
                     nodes: int,
                     ntask_per_node: int,
                     cpus_per_task: int,
                     mem: str = '0',
                     exclusive: bool = False,
                     ) -> None:
        """Submit a job to the cluster and return the job ID."""
        
        working_dir = os.path.abspath(working_dir)
        # 构建sbatch命令
        slurm_exclusive_option = '#SBATCH --exclusive\n' if exclusive else ''
        slurm_script = (
            rf'#!/bin/sh\n'
            rf'#SBATCH --job-name qdyn\n'
            rf'#SBTACH --partition={partition}\n'
            rf'#SBATCH --ntasks-per-node={ntask_per_node}\n'
            rf'#SBATCH --cpus-per-task={cpus_per_task}\n'
            rf'#SBATCH --mem={mem}\n'
            rf'#SBATCH --output=slurm-%j.out\n'
            rf'{slurm_exclusive_option}'
            rf'#SBTACH --parsable\n'
            rf'\n\n'
            rf'{dependency}\n\n'
            rf'cd {working_dir}\n'
            rf'{command}\n'
        )
        script_path = pjoin(working_dir, 'submit.sh')
        with open(script_path, 'w') as f:
            f.write(slurm_script)

        for task in self.tasks:
            if task.uuid == task_id:
                job_belongs_to_task = task
                break
        else:
            raise ValueError(f"Task with ID {task_id} not found in manager's task set.")

        job = Job(nodes=nodes, script_path=script_path, task=job_belongs_to_task)
        logging.info(f"Created job with UUID: {job.uuid} and script path: {script_path}.")




if __name__ == "__main__":
    manager = SlurmManager()
    task1 = Task(quota=2)
    manager.tasks.add(task1)

