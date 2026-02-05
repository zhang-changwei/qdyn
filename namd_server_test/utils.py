import os
import shutil
import re
import subprocess
from ase.io import read, write
import random
import numpy as np

def check_status(check_dir, step_index, force_recalculate=False):
    """
    Check for the existence of status files in the current directory.
    If any of the status files exist, print a message and return True.
    Otherwise, return False.
    """
    if os.path.exists(check_dir + '/RUNNING'):
        if force_recalculate:
            print("Forcing recalculate!")
            shutil.rmtree(check_dir)
            if os.path.exists("4_SCF") and step_index == 3:
                shutil.rmtree("4_SCF")
            return False
        else:
            raise RuntimeError("RUNNING file exists. Terminating the program to avoid duplicate execution.")
    elif os.path.exists(check_dir + '/ENDED'):
        print("Skipping this step as ENDED exists.")
        return True
    elif os.path.exists(check_dir + '/SUCCESSFUL'):
        print("Skipping this step as SUCCESSFUL exists.")
        return True
    elif os.path.exists(check_dir + '/FAILED'):
        shutil.rmtree(check_dir)
        if os.path.exists("4_SCF") and step_index == 3:
            shutil.rmtree("4_SCF")
        print("Failed before. Calculate again!")
        return False
    else:
        print("No status files found. Proceeding with the step.")
        return False

# Helper function for running shell commands
def run_command(command, check=True):
    try:
        result = subprocess.run(command, shell=True, check=check, capture_output=True, text=True)
        print(result.stdout)
        if result.stderr:
            print(f"STDERR: {result.stderr}")
        return result
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {e.cmd}")
        print(f"Exit code: {e.returncode}")
        print(f"Output: {e.stdout}")
        print(f"Error output: {e.stderr}")
        return None
    
def update_queue(script_path, job_id, step_number):
    """
    Update the SLURM queue in the input file to the queue with the most idle nodes.

    Args:
        script_path (str): Path to the input file to be updated.
    """
    if not script_path:
        print("请提供输入文件名作为参数。")
        return

    try:
        # Step 1: 获取每个队列的 idle 节点数
        result = subprocess.run(
            ["sinfo", "-o", "%P %t %D %C"],
            capture_output=True,
            text=True,
            check=True
        )
        sinfo_output = result.stdout

        # Step 2: 解析 sinfo 输出，找到 idle 节点最多的队列
        max_idle = 0
        target_queue = ""
        for line in sinfo_output.splitlines():
            if "idle" in line:
                parts = line.split()
                queue = parts[0]
                if queue == "debug":
                    continue
                idle = int(re.sub(r"[^\d]", "", parts[2]))  # 提取 idle 数字
                if idle > max_idle:
                    max_idle = idle
                    target_queue = queue

        # 去除队列名称后的 * 号
        target_queue = target_queue.rstrip("*")

        # Step 3: 修改输入文件中的队列名称
        if target_queue:
            with open(script_path, "r") as file:
                lines = file.readlines()

            with open(script_path, "w") as file:
                for line in lines:
                    if line.startswith("#SBATCH -p"):
                        file.write(f"#SBATCH -p {target_queue}\n")
                    elif line.startswith("#SBATCH -J"):
                        file.write(f"#SBATCH -J job{job_id}_step{step_number}\n")
                    else:
                        file.write(line)

            print(f"{script_path} 文件已更新，队列设置为: {target_queue}")
        else:
            print("未找到空闲队列")
    except subprocess.CalledProcessError as e:
        print(f"Error executing sinfo: {e}")
    except FileNotFoundError:
        print(f"输入文件 {script_path} 不存在。")
    except Exception as e:
        print(f"发生错误: {e}")

def continue_calculation(forece_recalculate=False):
    """
    Continues the calculation by creating the next 'suc' directory,
    copying necessary files. Working in the step2.
    """
    
    # Step 1: Find the next available directory number
    i = 1
    while os.path.exists(f"{i}suc/ENDED"):
        i += 1
    
    # Step 2: Create the new directory
    new_dir = f"{i}suc"
    if os.path.isdir(new_dir):
        if os.path.exists(f"{new_dir}/RUNNING"):
            if forece_recalculate:
                print(f"Force recalculate! Removing {new_dir} directory.")
                shutil.rmtree(new_dir)
            else:
                raise RuntimeError(f"{new_dir} directory already exists with RUNNING file. Terminating to avoid duplicate execution.")
        else:
            shutil.rmtree(new_dir)
            print(f"Removed existing wrong {new_dir} directory.")
    os.makedirs(new_dir, exist_ok=True)
    print(f"Created directory: {new_dir}")
    
    # Step 3: Determine source directory for copying files
    prev_dir = f"{i-1}suc"
    if os.path.isdir(prev_dir):
        # Copy from previous successful directory
        files_to_copy = ["INCAR", "KPOINTS", "POTCAR"]
        for file in files_to_copy:
            src = os.path.join(prev_dir, file)
            if os.path.exists(src):
                shutil.copy2(src, new_dir)        
        # Copy CONTCAR as POSCAR
        contcar_src = os.path.join(prev_dir, "CONTCAR")
        poscar_dst = os.path.join(new_dir, "POSCAR")
        if os.path.exists(contcar_src):
            shutil.copy2(contcar_src, poscar_dst)                
        print(f"Copied files from {prev_dir} to {new_dir}.")
    else:
        # Copy from current directory
        files_to_copy = ["INCAR", "KPOINTS", "POTCAR"]
        for file in files_to_copy:
            if os.path.exists(file):
                shutil.copy2(file, new_dir)        
        # Copy CONTCAR as POSCAR
        if os.path.exists("CONTCAR"):
            shutil.copy2("CONTCAR", os.path.join(new_dir, "POSCAR"))
        print(f"Copied files from current directory to {new_dir}.")

    return new_dir

def genescf(NSCF=2000):
    
    CONFIGS = read('XDATCAR', format='vasp-xdatcar', index=':')
    NSW    = len(CONFIGS)               # The number of ionic steps
    if NSCF > NSW: 
        print("WARNING: NSCF > NSW, set NSCF = NSW")
        NSCF = NSW
    NDIGIT = len("{:d}".format(NSCF))   #
    PREFIX = '4_SCF/'    # run directories
    DFORM  = "/%%0%dd" % NDIGIT         # run dirctories format
    for ii in range(NSCF):              # write POSCARs
        p = CONFIGS[ii - NSCF]
        r = (PREFIX + DFORM) % (ii + 1)
        if not os.path.isdir(r): os.makedirs(r)
        write('{:s}/POSCAR'.format(r), p, vasp5=True, direct=True)

def generate_inicon(count=100, iniband=177, min_value=2, max_value=500):
    file_path = 'INICON'  # 文件路径
    width = 3
    unique_random_numbers = random.sample(range(min_value, max_value + 1), count)
    with open(file_path, 'w') as file:
        for number in unique_random_numbers:
            file.write(f"  {number:>{width}} {iniband}\n")  # 在每个数字后添加一个空格

def parse_range(input_str):
    """
    Parses a range string (e.g., "1-10 12") and returns a numpy array
    containing all the specified numbers.

    Args:
        input_str (str): The input string, where ranges are specified with "-" 
                         (e.g., "1-3") and individual numbers are separated by spaces.

    Returns:
        np.ndarray: A numpy array containing the specified numbers.
    """
    
    if input_str == "None":
        return "None"
    
    ranges = []
    # 按空格分割输入字符串
    parts = input_str.split()
    
    # for part in parts:
    #     if '-' in part:
    #         # 如果包含 "-", 解析为范围
    #         start, end = map(int, part.split('-'))
    #         ranges.extend(range(start, end + 1))  # 包含结束值
    #     else:
    #         # 否则解析为单个数字
    #         ranges.append(int(part))
    
    # # 转换为 numpy 数组
    # return np.array(ranges)

    for part in parts:
        if '-' in part:
            # 如果包含 "-", 解析为范围
            start, end = map(int, part.split('-'))
            ranges.append(f"np.arange({start - 1}, {end})")
        else:
            # 否则解析为单个数字
            ranges.append(f"np.array([{part - 1}])")
    
    # 返回 np.concatenate 的字符串形式
    return f"np.concatenate([{', '.join(ranges)}])"
