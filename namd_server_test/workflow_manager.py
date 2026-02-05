import os
import time
import logging
import gc  # Import garbage collector module
import numpy as np
import shutil
import subprocess
from slurm_manager import SlurmManager
from config import JOBS_DIR, SCRIPTS_DIR, TEMPLATE_DIR, NAMD_INP
from prepare import *
from postprocess import *

class WorkflowManager:
    def __init__(self):
        self.active_jobs = {}
        self.slurm_manager = SlurmManager()
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    def start_workflow(self, job_id, poscar_file, parameters):
        """启动5步计算工作流"""
        try:
            # 初始化任务状态
            self.active_jobs[job_id] = {
                'status': 'initializing',
                'current_step': 0,
                'steps': [
                    {'name': 'Structure Optimization', 'status': 'pending', 'slurm_id': None},
                    {'name': 'NVT Equilibrium', 'status': 'pending', 'slurm_id': None},
                    {'name': 'NVE Trajectory', 'status': 'pending', 'slurm_id': None},
                    {'name': 'WAVECAR Calculation', 'status': 'pending', 'slurm_id': None},
                    {'name': 'Hefei-NAMD Simulation', 'status': 'pending', 'slurm_id': None}
                ],
                'parameters': parameters,
                'start_time': time.time(),
                'last_update': time.time()
            }
            
            # 创建工作目录
            job_dir = os.path.join(JOBS_DIR, job_id)
            os.makedirs(job_dir, exist_ok=True)
            
            # 保存POSCAR文件
            step1_dir = os.path.join(job_dir, 'step1')
            if parameters['new_job'] == 'True':
                os.makedirs(step1_dir, exist_ok=True)
                poscar_file.save(os.path.join(step1_dir, 'POSCAR'))
            
            # 进入工作目录
            os.chdir(job_dir)

            # 更新状态
            self.active_jobs[job_id]['status'] = 'ready'
            self.active_jobs[job_id]['steps'][0]['status'] = 'submitted'
            
            # 开始执行工作流
            self.execute_workflow(job_id, parameters)
            
        except Exception as e:
            logging.error(f"Workflow failed for job {job_id}: {str(e)}")
            self.active_jobs[job_id]['status'] = 'failed'
            self.active_jobs[job_id]['error'] = str(e)

    def execute_workflow(self, job_id, parameters):
        """执行5步计算流程"""
        job = self.active_jobs[job_id]
        job_dir = os.path.join(JOBS_DIR, job_id)
        force_recalculate = parameters.get('force_recalculate', 'False')
        try:
            # 第1步：结构优化
            if os.path.isdir("step1") and check_status("step1", 0, force_recalculate):
                logging.info("Step 1 already completed, skipping Structure Optimization.")
                job['current_step'] = 0
                job['steps'][0]['status'] = 'completed'
                if os.path.exists("step1/ENDED"):
                    logging.info("Step 1 ENDED exists, running postprocess.")
                    self.run_postprocess(job_id, 0, parameters)                    
            else:
                Job_initialize(parameters)
                self.run_step(job_id, 0, 'step1', 'sub_vasp')
                self.run_postprocess(job_id, 0, parameters)
            
            # 第2步：NVT平衡
            if os.path.isdir("step2") and check_status("step2", 1, force_recalculate):
                logging.info("Step 2 already completed, skipping NVT Equilibrium.")
                job['current_step'] = 1
                job['steps'][1]['status'] = 'completed'
                if os.path.exists("step2/ENDED"):
                    logging.info("Step 2 ENDED exists, running postprocess.")
                    self.run_postprocess(job_id, 1, parameters)
            else:
                prepare_nvt(parameters)
                self.run_step(job_id, 1, 'step2', 'sub_vasp')
                self.run_postprocess(job_id, 1, parameters)
            
            # 第3步：NVE轨迹
            if os.path.isdir("step3") and check_status("step3", 2, force_recalculate):
                logging.info("Step 3 already completed, skipping NVE Trajectory.")
                job['current_step'] = 2
                job['steps'][2]['status'] = 'completed'
                if os.path.exists("step3/ENDED"):
                    logging.info("Step 3 ENDED exists, running postprocess.")
                    self.run_postprocess(job_id, 2, parameters)
            else:
                prepare_nve(parameters)
                self.run_step(job_id, 2, 'step3', 'sub_vasp')
                self.run_postprocess(job_id, 2, parameters)
            
            # 第4步：WAVECAR计算
            if os.path.isdir("step4") and check_status("step4", 3, force_recalculate):
                logging.info("Step 4 already completed, skipping WAVECAR Calculation.")
                job['current_step'] = 3
                job['steps'][3]['status'] = 'completed'
                if os.path.exists("step4/ENDED"):
                    logging.info("Step 4 ENDED exists, running postprocess.")
                    self.run_postprocess(job_id, 3, parameters)
            else:
                prepare_scf(parameters, job_id)
                self.run_scf(job_id, 3, 'step4')
                self.run_postprocess(job_id, 3, parameters)
            
            # 第5步：Hefei-NAMD计算
            if os.path.isdir(NAMD_INP.get('dirname', 'step5')) and check_status(NAMD_INP.get('dirname', 'step5'), 4, force_recalculate):
                logging.info("Step 5 already completed, skipping Hefei-NAMD Simulation.")
                job['current_step'] = 4
                job['steps'][4]['status'] = 'completed'
                # if os.path.exists("step5/ENDED"):
                #     logging.info("Step 5 ENDED exists, running postprocess.")
                #     self.run_postprocess(job_id, 4)
            else:
                prepare_namd(parameters, NAMD_INP)
                self.run_step(job_id, 4, NAMD_INP.get('dirname', 'step5'), 'namd_sub')
                # self.run_postprocess(job_id, 4)
            
            # 完成工作流
            job['status'] = 'completed'
            job['end_time'] = time.time()
            logging.info(f"Job {job_id} completed successfully")
            
        except Exception as e:
            logging.error(f"Workflow failed at step {job['current_step'] + 1} for job {job_id}: {str(e)}")
            # 在出错目录标记失败
            if os.path.exists('RUNNING'):
                os.rename('RUNNING', 'FAILED')
            elif os.path.exists('ENDED'):
                os.rename('ENDED', 'FAILED')
            else:
                with open('FAILED', 'w') as f:
                    pass
            job['status'] = 'failed'
            job['error'] = str(e)
            job['steps'][job['current_step']]['status'] = 'failed'

    def run_step(self, job_id, step_index, step_dir, slurm_script):
        """提交计算步骤到Slurm"""
        job = self.active_jobs[job_id]
        job['current_step'] = step_index
        job['status'] = f'running step {step_index+1}'
        job['steps'][step_index]['status'] = 'submitted'
        
        # 获取步骤目录和脚本路径
        job_dir = os.path.join(JOBS_DIR, job_id)
        step_path = os.path.join(job_dir, step_dir)
        script_path = os.path.join(SCRIPTS_DIR, slurm_script)

        os.chdir(step_path)

        # 创建一个名为RUNNING的空文件
        with open('RUNNING', 'w') as f:
            pass
        
        # 提交Slurm任务
        slurm_id = self.slurm_manager.submit_job(
            script_path, 
            step_path,
            job_id,
            step_index + 1
        )
        
        # 记录Slurm任务ID
        job['steps'][step_index]['slurm_id'] = slurm_id
        job['steps'][step_index]['status'] = 'running'
        
        time.sleep(10)

        # 等待任务完成
        while not self.slurm_manager.job_completed(slurm_id):
            time.sleep(600)  # 每10分钟检查一次
            
        # 检查任务是否成功
        if not self.slurm_manager.job_successful(slurm_id):
            os.rename('RUNNING', 'FAILED')
            raise RuntimeError(f"Step {step_index+1} failed with Slurm ID {slurm_id}")
        
        job['steps'][step_index]['status'] = 'completed'
        logging.info(f"Step {step_index+1} completed for job {job_id} with Slurm ID {slurm_id}")

        # 将RUNNING文件改名为ENDED
        os.rename('RUNNING', 'ENDED')

        os.chdir(job_dir)

    def run_scf(self, job_id, step_index, step_dir):
        """提交SCF计算步骤到Slurm"""
        job = self.active_jobs[job_id]
        job['current_step'] = step_index
        job['status'] = f'running step {step_index+1}'
        job['steps'][step_index]['status'] = 'submitted'
        
        # 获取步骤目录和脚本路径
        job_dir = os.path.join(JOBS_DIR, job_id)
        step_path = os.path.join(job_dir, step_dir)

        os.chdir(step_path)

        # 创建一个名为RUNNING的空文件
        with open('RUNNING', 'w') as f:
            pass

        # 获取当前目录下所有以vasp开头的文件
        vasp_files = [f for f in os.listdir('.') if f.startswith('vasp')]
        slurm_ids = []
        for vasp_file in vasp_files:
            # 提交Slurm任务
            slurm_id = self.slurm_manager.submit_job(vasp_file, '.', job_id, step_index + 1, update=False)
            slurm_ids.append(slurm_id)
        
        # 记录Slurm任务ID
        job['steps'][step_index]['slurm_id'] = slurm_ids
        job['steps'][step_index]['status'] = 'running'

        time.sleep(10)
        
        while not self.slurm_manager.job_completed(slurm_ids[-1]):
            time.sleep(600)  # 每30秒检查一次

        # 等待所有任务完成
        while not all(self.slurm_manager.job_completed(slurm_id) for slurm_id in slurm_ids):
            time.sleep(300)  # 每30秒检查一次

        # 检查所有任务是否成功
        if not all(self.slurm_manager.job_successful(slurm_id) for slurm_id in slurm_ids):
            os.rename('RUNNING', 'FAILED')
            raise RuntimeError(f"Step {step_index+1} failed. One or more Slurm jobs were unsuccessful.")

        job['steps'][step_index]['status'] = 'completed'
        logging.info(f"Step 4 completed for job {job_id}")

        # 将RUNNING文件改名为ENDED
        os.rename('RUNNING', 'ENDED')

        os.chdir(job_dir) # cd center dir

    def run_postprocess(self, job_id, step_index, parameters, recursion_depth=0):
        """运行后处理脚本"""
        step_dir = f"step{step_index+1}"
        job_dir = os.path.join(JOBS_DIR, job_id)
        step_path = os.path.join(job_dir, step_dir)
        os.chdir(step_path) # cd step2

        if step_index == 0:
            self.check_convergence(job_id)
        elif step_index == 1:
            self.check_nvt(job_id, parameters, step_path, recursion_depth=recursion_depth)
        elif step_index == 2:   
            self.check_nve(job_id, parameters)
        elif step_index == 3:
            self.check_wavecar(job_id)

        os.chdir(job_dir)

    def check_convergence(self, job_id):
        print("Checking convergence...")
        if not os.path.isfile('OUTCAR'):
            logging.error(f"Step 1 failed for job {job_id}: OUTCAR file not found")
            raise RuntimeError(f"Step 1 failed for job {job_id}: OUTCAR file not found")
        
        with open('OUTCAR', 'r') as f:
            lines = f.readlines()
        
        for line in reversed(lines):
            if 'reached required accuracy' in line or 'reached required accuracy for' in line:
                os.rename('ENDED', 'SUCCESSFUL')
                logging.info(f"Step 1 succeeded for job {job_id}")
                break
            if 'energy  without entropy' in line:
                os.rename('ENDED', 'FAILED')
                logging.error(f"Step 1 failed for job {job_id}")
                raise RuntimeError(f"Step 1 failed for job {job_id}: Not converged")
        
    def check_nvt(self, job_id, parameters, step_path, recursion_depth=0):
        """step_path: the absolute path of step2"""
        
        MAX_RECURSION_DEPTH = 10  # 设置递归次数上限

        if recursion_depth > MAX_RECURSION_DEPTH:
            os.rename('ENDED', 'FAILED')
            logging.error(f"Step 2 failed for job {job_id}: Exceeded maximum recursion depth ({MAX_RECURSION_DEPTH}).")
            raise RuntimeError(f"Step 2 failed for job {job_id}: Exceeded maximum recursion depth ({MAX_RECURSION_DEPTH}).")

        logging.info("Checking NVT results...")
        
        # cd latest dir
        i = 1
        while os.path.exists(f"{i}suc/ENDED"):
            i += 1
        prev_dir = f"{i-1}suc"
        if os.path.isdir(prev_dir):
            os.chdir(prev_dir)
        else:
            pass

        temperature = parameters.get('temperature', 300)
        nsw = parameters.get('nvt_steps', 1000)
        check_nsw = nsw // 20
        max_unconverged = nsw // 10
        
        is_converged = check_md_convergence(check_nsw, max_unconverged, self.active_jobs[job_id]['steps'][1]['slurm_id'])
        if is_converged:
            nvt_temp = plot_nvt()[-1000:]
            nvt_temp = np.array(nvt_temp)
            nvt_temp -= temperature
            abs_nvt_max = max(abs(nvt_temp))
            if abs_nvt_max <= temperature * 0.10:  # 0.20 ?
                os.chdir(step_path)
                os.rename('ENDED', 'SUCCESSFUL')
                logging.info(f"Step 2 completed for job {job_id}")
                return True
            else:
                logging.info("NVT not converged, continuing calculation...")
                os.chdir(step_path)
                new_dir = continue_calculation()
                working_dir = os.path.join("step2", new_dir)
                del nvt_temp, abs_nvt_max, prev_dir, i  # Delete unnecessary variables
                gc.collect()  # Force garbage collection to free memory
                self.run_step(job_id, 1, working_dir, 'sub_vasp')
                return self.run_postprocess(job_id, 1, parameters, recursion_depth=recursion_depth + 1)
        else:
            os.chdir(step_path)
            os.rename('ENDED', 'FAILED')
            logging.error(f"Step 2 failed for job {job_id}: NVT is hard to converge, suggesting to check in detail!")
            raise RuntimeError(f"Step 2 failed for job {job_id}: NVT is hard to converge, suggesting to check in detail!")
        
    def check_nve(self, job_id, parameters):
        print("Checking NVE...")
        check_nsw = parameters.get('wavecar_steps', 500) + 100
        nsw = parameters.get('nve_steps', 1000)
        max_unconverged = nsw // 100
        
        is_converged = check_md_convergence(check_nsw, max_unconverged, self.active_jobs[job_id]['steps'][2]['slurm_id'])
        if is_converged:
            plot_tdks()
            os.rename('ENDED', 'SUCCESSFUL')
            logging.info(f"Step 3 completed for job {job_id}")
        else:
            os.rename('ENDED', 'FAILED')
            logging.error(f"Step 3 failed for job {job_id}: NVE not converged in the last {check_nsw} steps, suggesting to check in detail!")
            raise RuntimeError(f"Step 3 failed for job {job_id}: NVE not converged in the last {check_nsw} steps, suggesting to check in detail!")
        
    def check_wavecar(self, job_id):
        # logging.info("Checking SCF convergence...")
        # slurm_ids = self.active_jobs[job_id]['steps'][3]['slurm_id']
        # for slurm_id in slurm_ids:
        #     slurm_file = f"slurm-{slurm_id}.out"
        #     if not os.path.isfile(slurm_file):
        #         logging.error(f"Slurm file {slurm_file} not found in the current directory.")
        #         raise RuntimeError(f"Slurm file {slurm_file} not found in the current directory.")
        #     with open(slurm_file, 'r') as f:
        #         lines = f.readlines()
        #         for line in lines:
        #             if 'self-consistency was not achieved' in line:
        #                 os.rename('ENDED', 'FAILED')
        #                 logging.error(f"Step 4 failed for job {job_id}: SCF not converged, suggesting to check in detail!")
        #                 raise RuntimeError(f"Step 4 failed for job {job_id}: SCF not converged, suggesting to check in detail!")

        logging.info("All SCF converged, checking WAVECAR files...")
        try:
            wavecar_files = glob.glob("../4_SCF/*/WAVECAR")
            if not wavecar_files:
                raise FileNotFoundError("No WAVECAR files found in 4_SCF subdirectories.")                
                # Get all unique file sizes
            file_sizes = {os.path.getsize(f) for f in wavecar_files}
            print(f"Found {len(file_sizes)} unique WAVECAR size(s).")
            if len(file_sizes) > 1:
                raise ValueError("WAVECAR file sizes are not consistent. Exiting program.")
            else:
                logging.info(f"Step 4 completed for job {job_id}")
                self.run_step(job_id, 3, '.', 'python_sub') # cd job_dir; run tdksen.py
                os.remove('ENDED')
                os.rename('step4/ENDED', 'step4/SUCCESSFUL')
        except FileNotFoundError as e:
            raise FileNotFoundError(f"Error: Could not access 4_SCF directory or its contents. Details: {str(e)}")

    def get_job_status(self, job_id):
        """获取任务状态"""
        if job_id not in self.active_jobs:
            return {'error': 'Job not found'}
        
        job = self.active_jobs[job_id]
        
        # 更新运行中步骤的状态
        for step in job['steps']:
            if step['status'] == 'running' and step['slurm_id']:
                if self.slurm_manager.job_completed(step['slurm_id']):
                    if self.slurm_manager.job_successful(step['slurm_id']):
                        step['status'] = 'completed'
                    else:
                        step['status'] = 'failed'
                        job['status'] = 'failed'
        
        return job