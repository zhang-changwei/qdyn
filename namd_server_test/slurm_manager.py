import subprocess
import re
import logging
from config import SCRIPTS_DIR
from utils import update_queue

class SlurmManager:
    def submit_job(self, script_path, working_dir, job_id, step_number, update=True):
        """提交Slurm任务"""
        
        if update:
            # 动态更新队列
            update_queue(script_path, job_id, step_number)

        # 提交任务
        result = subprocess.run(
            ['sbatch', script_path],
            capture_output=True,
            text=True,
            cwd=working_dir # working in working_dir
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Slurm submission failed: {result.stderr}")
        
        # 提取任务ID
        match = re.search(r'Submitted batch job (\d+)', result.stdout)
        if not match:
            raise RuntimeError("Failed to extract Slurm job ID")
        
        return match.group(1)

    def job_completed(self, job_id):
        """检查任务是否完成"""
        result = subprocess.run(
            ['sacct', '-j', job_id, '--format=State', '--noheader'],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            return False
        
        # 检查任务状态
        states = result.stdout.strip().split('\n')
        for state in states:
            if not states or states == ['']:
                logging.warning(f"No state information found for slurm job {job_id}. It might be due to job not starting yet. \
                                Please wait for seconds and check again.")
                return False
            elif state and 'COMPLETED' not in state and 'FAILED' not in state and 'CANCELLED' not in state:
                logging.info(f"Slurm job {job_id} is still running or pending with state: {state}")
                return False
        logging.info(f"Slurm job {job_id} is {state}.")
        return True

    def job_successful(self, job_id):
        """检查任务是否成功完成"""
        result = subprocess.run(
            ['sacct', '-j', job_id, '--format=State', '--noheader'],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            return False
        
        # 检查任务状态
        states = result.stdout.strip().split('\n')
        for state in states:
            if state and 'COMPLETED' not in state:
                logging.warning(f"Slurm job {job_id} failed with state: {state}")
                return False
        logging.info(f"Slurm job {job_id} is successful.")
        return True