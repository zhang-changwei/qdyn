#!/usr/bin/env python3
"""
VASP-NAMD自动化工作流测试脚本
直接在集群上运行，无需Web界面
"""

import os
import sys
import time
import logging
import shutil
from workflow_manager import WorkflowManager
from config import JOBS_DIR, SCRIPTS_DIR, DEFAULT_PARAMETERS

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("workflow_test.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

class TestWorkflow:
    def __init__(self):
        self.workflow_manager = WorkflowManager()
        
    def run_test(self, poscar_path, job_id=None, parameters=None):
        """运行完整的VASP-NAMD工作流测试"""
        # 使用默认参数如果未提供
        if parameters is None:
            parameters = DEFAULT_PARAMETERS.copy()
        
        # 生成任务ID如果未提供
        if job_id is None:
            job_id = f"test_{int(time.time())}"
        
        logging.info(f"Starting workflow test with job ID: {job_id}")
        logging.info(f"Using POSCAR: {poscar_path}")
        logging.info(f"Parameters: {parameters}")
        
        # 复制POSCAR文件到工作目录
        job_dir = os.path.join(JOBS_DIR, job_id, "step1")
        os.makedirs(job_dir, exist_ok=True)
        # dest_poscar = os.path.join(job_dir, "POSCAR")
        # shutil.copy(poscar_path, dest_poscar)
        
        # 创建模拟的文件对象
        class MockFile:
            def __init__(self, path):
                self.path = path
                self.filename = os.path.basename(path)
            
            def save(self, dest):
                shutil.copy2(self.path, dest)
        
        mock_file = MockFile(poscar_path)
        
        # 启动工作流
        try:
            self.workflow_manager.start_workflow(job_id, mock_file, parameters)
            
            # 监控工作流状态
            while True:
                status = self.workflow_manager.get_job_status(job_id)
                
                if status.get('status') in ['completed', 'failed']:
                    break
                
                # 打印当前状态
                current_step = status.get('current_step', 0)
                step_status = status.get('steps', [])[current_step].get('status', 'unknown') if current_step < len(status.get('steps', [])) else 'unknown'
                
                logging.info(f"Step {current_step + 1}: {step_status}")
                time.sleep(30)  # 每30秒检查一次
            
            # 最终状态
            final_status = self.workflow_manager.get_job_status(job_id)
            logging.info(f"Workflow completed with status: {final_status.get('status')}")
            
            if final_status.get('status') == 'completed':
                logging.info("Workflow completed successfully!")
                return True
            else:
                logging.error(f"Workflow failed: {final_status.get('error', 'Unknown error')}")
                return False
                
        except Exception as e:
            logging.error(f"Workflow test failed: {str(e)}")
            return False

def main():
    """主函数"""
    # # 检查参数
    # if len(sys.argv) < 2:
    #     print("Usage: python run_workflow_test.py <path_to_POSCAR> [job_id]")
    #     print("Example: python run_workflow_test.py /path/to/POSCAR my_test_job")
    #     sys.exit(1)
    
    # 获取POSCAR路径
    # poscar_path = sys.argv[1]
    poscar_path = './jobs/POSCAR'
    
    # 获取可选的job_id
    # job_id = sys.argv[2] if len(sys.argv) > 2 else None
    job_id = "111"
    
    # 自定义参数（可选）
    custom_parameters = {
    'new_job': 'False',
    'temperature': 300,
    'nvt_steps': 1000,
    'nve_steps': 1000,
    'wavecar_steps': 500,
    'whichA': 'None', 
    'simulation_method': 'FSSH',
    'INIBAND': 4,
    'simulation_time': 400
}
    
    # 运行测试
    test = TestWorkflow()
    success = test.run_test(poscar_path, job_id, custom_parameters)
    
    if success:
        print("Workflow test completed successfully!")
        sys.exit(0)
    else:
        print("Workflow test failed!")
        sys.exit(1)

if __name__ == "__main__":
    main()
