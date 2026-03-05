import asyncio
import os
from os.path import join as pjoin
import pathlib
import subprocess
import uuid
import logging
from contextlib import asynccontextmanager
from typing import List, Optional, Dict
import yaml

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .constants import JOB_MANAGER_POLL_INTERVAL


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------

class Task:
    def __init__(self, quota: int):
        self.uuid = str(uuid.uuid4())
        self.quota: int = quota
        self.used: int = 0


class Job:
    def __init__(self, nodes: int, script_path: str, task: Task):
        self.uuid = str(uuid.uuid4())
        self.job_id: int = 0
        self.status: str = 'waiting'
        self.nodes = nodes
        self.script_path = script_path
        self.retry: int = 0
        self.task: Task = task


# ---------------------------------------------------------------------------
# SLURM manager
# ---------------------------------------------------------------------------

class SlurmManager:

    def __init__(self):
        self.tasks: List[Task] = []
        self.jobs: List[Job] = []
        self._poll_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Background poll loop
    # ------------------------------------------------------------------

    def start_polling(self) -> None:
        """Schedule the poll loop as an asyncio background task."""
        self._poll_task = asyncio.create_task(self._poll_loop())
        logging.info("SlurmManager poll loop started.")

    def stop_polling(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            logging.info("SlurmManager poll loop stopped.")

    async def _poll_loop(self) -> None:
        while True:
            await asyncio.sleep(JOB_MANAGER_POLL_INTERVAL)
            try:
                self.check_job_status()
                self.submit_jobs()
            except Exception:
                logging.exception("Error during poll cycle.")

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def submit_jobs(self) -> None:
        for job in self.jobs:
            if job.status == 'waiting' and job.task.used + job.nodes <= job.task.quota:
                result = subprocess.run(
                    ['sbatch', '--parsable', job.script_path],
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    logging.error(f"Slurm submission failed for job {job.uuid}: {result.stderr}")
                    job.status = 'failed'
                    continue

                # --parsable output: "<jobid>" or "<jobid>;<cluster>"
                try:
                    job.job_id = int(result.stdout.strip().split(';')[0])
                    job.status = 'pending'
                    job.task.used += job.nodes
                    logging.info(f"Submitted job {job.uuid} → Slurm ID {job.job_id}.")
                except ValueError:
                    logging.error(f"Cannot parse Slurm job ID from output: {result.stdout!r}")
                    job.status = 'failed'

    def check_job_status(self) -> None:
        running_jobs = [j for j in self.jobs if j.status in ('pending', 'running')]
        if not running_jobs:
            return

        job_ids = [str(j.job_id) for j in running_jobs]
        result = subprocess.run(
            ['sacct', '-j', ','.join(job_ids),
             '--format=JobID,State', '--noheader', '-X'],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logging.warning(f"sacct failed: {result.stderr}")
            return

        id_to_job = {j.job_id: j for j in running_jobs}
        for line in result.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                slurm_id = int(parts[0])
            except ValueError:
                continue
            state = parts[1].lower()

            job = id_to_job.get(slurm_id)
            if job is None:
                continue

            job.status = state
            if state not in ('pending', 'running'):
                job.task.used -= job.nodes
                logging.info(f"Job {job.uuid} (Slurm {slurm_id}) finished with state '{state}'.")

    # ------------------------------------------------------------------
    # Task management
    # ------------------------------------------------------------------

    def add_task(self, quota: int, config: Dict) -> str:
        if not self.tasks:
            logging.info("Creating first task with quota=1.")
            quota = 1
            task = Task(quota=quota)
            self.tasks.append(task)

            file_path = os.path.abspath(__file__)
            main_path = pathlib.Path(file_path).parent / 'main.py'
            
            self.register_job(
                task.uuid, 
                command=(
                    f'export OMP_NUM_THREADS={config['scheduler']['cpus_per_node']}\n'
                    f'python {main_path}'
                ),
                working_dir=str(main_path.parent),
                partition=config['scheduler']['partition'],
                nodes=1,
                ntasks_per_node=1,
                cpus_per_task=config['scheduler']['cpus_per_node'],
                exclusive=True,
            )
        else:
            task = Task(quota=quota)
            self.tasks.append(task)
            logging.info(f"Created task {task.uuid} with quota={quota}.")
        return task.uuid

    def delete_task(self, task_id: str) -> None:
        for i, task in enumerate(self.tasks):
            if task.uuid == task_id:
                self.tasks.pop(i)
                logging.info(f"Deleted task {task_id}.")
                return
        raise ValueError(f"Task {task_id} not found.")

    # ------------------------------------------------------------------
    # Job registration
    # ------------------------------------------------------------------

    def register_job(
        self,
        task_id: str,
        command: str,
        working_dir: str,
        partition: str,
        nodes: int,
        ntasks_per_node: int,
        cpus_per_task: int,
        dependency: str = '',
        mem: str = '0',
        exclusive: bool = False,
    ) -> str:
        """Write a SLURM batch script and enqueue the job."""

        for task in self.tasks:
            if task.uuid == task_id:
                break
        else:
            raise ValueError(f"Task {task_id} not found.")

        working_dir = os.path.abspath(working_dir)
        os.makedirs(working_dir, exist_ok=True)

        exclusive_line = '#SBATCH --exclusive\n' if exclusive else ''
        dependency_line = f'#SBATCH --dependency={dependency}\n' if dependency else ''

        slurm_script = (
            f'#!/bin/sh\n'
            f'#SBATCH --job-name=qdyn\n'
            f'#SBATCH --partition={partition}\n'
            f'#SBATCH --nodes={nodes}\n'
            f'#SBATCH --ntasks-per-node={ntasks_per_node}\n'
            f'#SBATCH --cpus-per-task={cpus_per_task}\n'
            f'#SBATCH --mem={mem}\n'
            f'#SBATCH --output=slurm-%j.out\n'
            f'{exclusive_line}'
            f'{dependency_line}'
            f'\n'
            f'cd {working_dir}\n'
            f'{command}\n'
        )

        script_path = pjoin(working_dir, 'submit.sh')
        with open(script_path, 'w') as f:
            f.write(slurm_script)

        job = Job(nodes=nodes, script_path=script_path, task=task)
        self.jobs.append(job)
        logging.info(f"Registered job {job.uuid} for task {task_id}.")
        return job.uuid


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

manager = SlurmManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    manager.start_polling()
    yield
    manager.stop_polling()


app = FastAPI(title="QDYN Job Manager", lifespan=lifespan)


# --- Request / response schemas ---

class TaskCreate(BaseModel):
    quota: int


class TaskInfo(BaseModel):
    uuid: str
    quota: int
    used: int


class JobRegister(BaseModel):
    task_id: str
    command: str
    working_dir: str
    partition: str
    nodes: int
    ntasks_per_node: int
    cpus_per_task: int
    dependency: str = ''
    mem: str = '0'
    exclusive: bool = False


class JobInfo(BaseModel):
    uuid: str
    job_id: int
    status: str
    nodes: int
    task_id: str


# --- Task endpoints ---

@app.post("/tasks", response_model=TaskInfo, status_code=201)
def create_task(body: TaskCreate):
    task_id = manager.add_task(body.quota)
    task = next(t for t in manager.tasks if t.uuid == task_id)
    return TaskInfo(uuid=task.uuid, quota=task.quota, used=task.used)


@app.get("/tasks", response_model=List[TaskInfo])
def list_tasks():
    return [TaskInfo(uuid=t.uuid, quota=t.quota, used=t.used) for t in manager.tasks]


@app.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: str):
    try:
        manager.delete_task(task_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- Job endpoints ---

@app.post("/jobs", response_model=JobInfo, status_code=201)
def register_job(body: JobRegister):
    try:
        job_id = manager.register_job(**body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    job = next(j for j in manager.jobs if j.uuid == job_id)
    return JobInfo(uuid=job.uuid, job_id=job.job_id, status=job.status,
                   nodes=job.nodes, task_id=job.task.uuid)


@app.get("/jobs", response_model=List[JobInfo])
def list_jobs():
    return [
        JobInfo(uuid=j.uuid, job_id=j.job_id, status=j.status,
                nodes=j.nodes, task_id=j.task.uuid)
        for j in manager.jobs
    ]


@app.get("/jobs/{job_uuid}", response_model=JobInfo)
def get_job(job_uuid: str):
    for j in manager.jobs:
        if j.uuid == job_uuid:
            return JobInfo(uuid=j.uuid, job_id=j.job_id, status=j.status,
                           nodes=j.nodes, task_id=j.task.uuid)
    raise HTTPException(status_code=404, detail=f"Job {job_uuid} not found.")


