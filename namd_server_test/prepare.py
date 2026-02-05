import os
import shutil
import glob
import fileinput
import re
# import logging
from config import TEMPLATE_DIR, SCRIPTS_DIR
from utils import *

def Job_initialize(parameters):
    """
    Job_initialize for structure relaxation (SR)
    """

    os.chdir("step1")

    shutil.copy2(os.path.join(TEMPLATE_DIR, "VASP/INCAR"), "INCAR")

    # Concatenate INCAR and 1_SRincar into a new INCAR file
    with open("INCAR", "r") as incar_file, open(os.path.join(TEMPLATE_DIR, "VASP/1_SRincar"), "r") as srincar_file:
        incar_content = incar_file.read()
        srincar_content = srincar_file.read()

    with open("INCAR", "w") as incar_file:
        incar_file.write(incar_content + '\n' + srincar_content)

    # add costum INCAR tags    

    # Create POTCAR and KPOINTS
    run_command("echo -e \"103\" | vaspkit")
    run_command("echo -e \"102\n2\n0.02\" | vaspkit")
    shutil.copy2("POTCAR", "../POTCAR")
    
    # Modify INCAR to set ENCUT
    with open("POTCAR", "r") as potcar_file:
        enmax_values = [
            float(line.split()[2].rstrip(";"))
            for line in potcar_file if "ENMAX" in line
        ]
    ENMAX = max(enmax_values)
    with open("INCAR", "r") as file:
        lines = file.readlines()  # 一次性读取整个文件
    with open("INCAR", "w") as file:
        for line in lines:
            if "ENCUT" in line:
                file.write(f"ENCUT  = {ENMAX * 1.3:.0f}\n")  # 修改 ENCUT
            else:
                file.write(line)  # 保留其他行

    # now in the step1

    os.chdir("..")

def prepare_nvt(parameters):
    """
    Run NVT calculation setup
    """
    
    # Step 1: Create directory step2
    os.makedirs("step2", exist_ok=True)
    
    # Step 2: Copy files from 1_sc to step2
    files_to_copy = ["INCAR", "CONTCAR", "KPOINTS"]
    for file in files_to_copy:
        src = f"step1/{file}"
        dst = f"step2/{file}"
        if os.path.exists(src):
            shutil.copy2(src, dst)
    
    # Step 4: Change to step2 directory
    os.chdir("step2")

    # Link POTCAR
    potcar_link = "POTCAR"
    if not os.path.exists(potcar_link):
        os.symlink("../POTCAR", potcar_link)
    
    # Step 5: Modify INCAR
    with open("INCAR", "r") as incar_file, open(os.path.join(TEMPLATE_DIR, "VASP/2_NVTincar"), "r") as nvt_file:
        incar_lines = incar_file.readlines()
        nvt_lines = nvt_file.readlines()

    with open("INCAR", "w") as incar_file:
        for line in incar_lines:
            if re.search(r'.*LREAL.*', line):
                incar_file.write("LREAL  =  Auto\n")
            elif re.search(r'.*PREC.*', line):
                incar_file.write("# PREC   =  Accurate\n")
            elif line.startswith("STEP1"):
                break
            else:
                incar_file.write(line)
        # incar_file.write("\n")
        for line in nvt_lines:
            if line.startswith("NSW"):
                incar_file.write(f"NSW     = {parameters.get('nvt_steps', 1000)}\n")
            elif line.startswith("TEBEG"):
                incar_file.write(f"TEBEG   = {parameters.get('temperature', 300)}\n")
            elif line.startswith("TEEND"):
                incar_file.write(f"TEEND   = {parameters.get('temperature', 300)}\n")
            else:
                incar_file.write(line)

    # Step 6: Rename CONTCAR to POSCAR
    if os.path.exists("CONTCAR"):
        os.rename("CONTCAR", "POSCAR")
    
    # Step 7: Calculate natom and truncate POSCAR
    try:
        with open("POSCAR", "r") as poscar_file:
            lines = poscar_file.readlines()
            # Get line 7 (index 6) and extract numbers
            line7 = lines[6].strip()
            numbers = re.findall(r'\d+', line7)
            natom = sum(int(num) for num in numbers)
            print(f"Number of atoms: {natom}")
            parameters["natoms"] = natom
            # Keep only lines up to natom+8 (since we're 0-indexed, line natom+9 becomes index natom+8)
            truncated_lines = lines[:natom+8]
                
        with open("POSCAR", "w") as poscar_file:
            poscar_file.writelines(truncated_lines)

    except (FileNotFoundError, IndexError, ValueError) as e:
        print(f"Error processing POSCAR: {e}")
    
    run_command("echo -e \"102\n2\n0.04\" | vaspkit")

    # Step 10: Go back to parent directory
    os.chdir("..")

def prepare_nve(parameters):
    """
    Run NVE calculation setup
    
    """
    # Step 1: Create directory step3
    os.makedirs("step3", exist_ok=True)
    
    # Step 2: Find the latest CONTCAR file in step2 directory
    contcar_files = glob.glob("step2/**/CONTCAR", recursive=True)
    
    if contcar_files:
        # Sort files by modification time, newest last
        latest_contcar = max(contcar_files, key=os.path.getmtime)
        print(f"最新的 CONTCAR 文件是: {latest_contcar}")
        
        # Copy the latest CONTCAR file as POSCAR
        shutil.copy(latest_contcar, "step3/POSCAR")
        print(f"已将 {latest_contcar} 复制为 step3/POSCAR")
    else:
        print("未找到任何 CONTCAR 文件")
        return
    
    # Step 3: Copy INCAR and KPOINTS from step2 to step3
    for file in ["INCAR", "KPOINTS"]:
        src = f"step2/{file}"
        dst = f"step3/{file}"
        if os.path.exists(src):
            shutil.copy(src, dst)
    
    # Step 5: Change to step3 directory
    os.chdir("step3")

    # Link POTCAR
    potcar_link = "POTCAR"
    if not os.path.exists(potcar_link):
        os.symlink("../POTCAR", potcar_link)    
    
    # Step 6: Modify INCAR
    with open("INCAR", "r") as incar_file, open(os.path.join(TEMPLATE_DIR, "VASP/3_NVEincar"), "r") as nve_file:
        incar_lines = incar_file.readlines()
        nve_lines = nve_file.readlines()

    with open("INCAR", "w") as incar_file:
        for line in incar_lines:
            if line.startswith("STEP2"):
                break
            else:
                incar_file.write(line)
        # incar_file.write("\n")
        for line in nve_lines:
            if line.startswith("NSW"):
                incar_file.write(f"NSW     = {parameters.get('nve_steps', 1000)}\n")
            else:
                incar_file.write(line)
    
    # Step 9: Go back to parent directory
    os.chdir("..")

def prepare_scf(parameters, job_id):
    """
    Prepares and submits SCF calculations.

    Args:
        nscf (int): Total number of SCF calculations.
        batch (int): Number of calculations per batch job.
    """

    # --- 1. SCF Directory Setup ---
    print("--- Setting up SCF directories ---")
    os.makedirs("4_SCF", exist_ok=True)
    
    files_to_copy = ["INCAR", "XDATCAR", "KPOINTS"]
    for file in files_to_copy:
        src = f"step3/{file}"
        dst = f"{file}"
        if os.path.exists(src):
            shutil.copy2(src, dst)

    nscf = parameters.get('wavecar_steps', 500)
    ndigit = len("{:d}".format(nscf))
    
    print("Running genescf to generate POSCAR files...")
    genescf(nscf)

    last_poscar = os.path.join("4_SCF", f"{nscf}", "POSCAR")
    if not os.path.exists(last_poscar):
        raise RuntimeError("Python script genescf.py failed to create SCF directories correctly.")
    print("SCF directories created successfully.")

    # --- 2. Plotting Script Modification ---
    print("\n--- Modifying plotting script ---")
    tdksen_path = os.path.join(SCRIPTS_DIR, "tdksen.py")
    if os.path.exists(tdksen_path):
        shutil.copy2(tdksen_path, "tdksen.py")
    else:
        print("Warning: tdksen.py not found in scripts directory.")

    with open("tdksen.py", "r") as tdksen_file, open("VBCB", "r") as vbcb_file:
        lines = tdksen_file.readlines()
        vbcb_lines = vbcb_file.readlines()
        for line in vbcb_lines:
            if "VBM_energy" in line:
                VBM_energy = float(line.split('=')[1].strip())
            elif "CBM_energy" in line:
                CBM_energy = float(line.split('=')[1].strip())
            elif "Band_gap" in line:
                band_gap = float(line.split('=')[1].strip())

    with open("tdksen.py", "w") as tdksen_file:
        for line in lines:
            if line.startswith("nsw  "):
                tdksen_file.write(f"nsw     = {nscf}\n")
            # elif line.startswith("whichS "):
            #     tdksen_file.write(f"whichS  = {VBM_energy:.4f}\n")
            # elif line.startswith("whichK "):
            #     tdksen_file.write(f"whichK  = {CBM_energy:.4f}\n")
            elif line.startswith("whichA "):
                atom = parse_range(parameters.get('whichA', 'None'))
                tdksen_file.write(f"whichA  = {atom}\n")
            elif line.startswith("ax.set_ylim"):
                tdksen_file.write(f"ax.set_ylim({VBM_energy - 0.5*band_gap:.4f}, {CBM_energy + 0.5*band_gap:.4f})\n")
            else:
                tdksen_file.write(line)

    # --- 3. INCAR Modification ---
    print("\n--- Modifying INCAR for SCF ---")
    with open("INCAR", "r") as incar_file, open(os.path.join(TEMPLATE_DIR, "VASP/4_SCFincar"), "r") as scf_file:
        incar_lines = incar_file.readlines()
        scf_content = scf_file.read()

    with open("INCAR", "w") as incar_file:
        for line in incar_lines:
            if re.search(r'.*ICHARG.*', line):
                incar_file.write("ICHARG =  1\n")
            elif re.search(r'.*PREC.*', line):
                incar_file.write("PREC   =  Accurate\n")
            elif re.search(r'.*LWAVE.*', line):
                incar_file.write("LWAVE  = .TRUE.\n")
            elif re.search(r'.*LCHARG.*', line):
                incar_file.write("LCHARG = .TRUE.\n")
            elif line.startswith("STEP3"):
                break
            else:
                incar_file.write(line)
        # incar_file.write("\n")
        incar_file.write(scf_content)
    print("INCAR modified and merged with 4_SCFincar.")

    # --- 4. Linking Files into Subdirectories ---
    print("\n--- Linking common files into SCF subdirectories ---")
    os.chdir("4_SCF")
    for i in range(1, nscf + 1):
        sub_dir = f"{i:0{ndigit}d}"
        os.chdir(sub_dir)
        for f in ["INCAR", "KPOINTS", "POTCAR"]:
            link_path = os.path.join("../..", f)
            if os.path.exists(f):
                os.remove(f)
            os.symlink(link_path, f)
        os.chdir("..")
    os.chdir("..")
    print("Linking complete.")

    # --- 5. Batch Job Submission ---
    print("\n--- Preparing and submitting batch jobs ---")
    # 读KPOINTS文件确认gamma or std
    with open("KPOINTS", "r") as file:
        lines = file.readlines()
        # 提取第 4 行并解析 kx, ky, kz
        kx, ky, kz = map(int, lines[3].split())
        
        # 计算 kx, ky, kz 的乘积
    kpoints_product = kx * ky * kz
    is_gamma = (kpoints_product == 1)
    
    update_queue(os.path.join(SCRIPTS_DIR, "vaspscf"), job_id, step_number=4)

    batch = max(100, nscf // 10)
    remainder = nscf % batch
    quotient = nscf // batch
    print(f"Total calculations: {nscf}, Batch size: {batch}")
    print(f"Quotient: {quotient}, Remainder: {remainder}")

    os.makedirs("step4", exist_ok=True)
    os.chdir("step4")

    # Modify full batches
    for i in range(1, quotient + 1):
        order = i * batch
        start = order - batch + 1
        job_script_name = f"vasp{order}"
        
        shutil.copy2(os.path.join(SCRIPTS_DIR, "vaspscf"), job_script_name)
        with open(job_script_name, "r") as file:
            lines = file.readlines()
        with open(job_script_name, "w") as file:
            for line in lines:
                if line.startswith("START="):
                    file.write(f"START={start}\n")
                elif line.startswith("END="):
                    file.write(f"END={order}\n")
                elif line.startswith("NDIGIT="):
                    file.write(f"NDIGIT={ndigit}\n")
                elif re.search(r'srun', line):
                    if is_gamma:
                        new_line = re.sub(r'vasp_std|vasp_gam', 'vasp_gam', line)
                        file.write(new_line)
                    else:
                        new_line = re.sub(r'vasp_std|vasp_gam', 'vasp_std', line)
                        file.write(new_line)
                else:
                    file.write(line)

    # Modify the remainder batch
    if remainder != 0:
        start = quotient * batch + 1
        job_script_name = f"vasp{nscf}"
        
        shutil.copy(os.path.join(SCRIPTS_DIR, "vaspscf"), job_script_name)
        with open(job_script_name, "r") as file:
            lines = file.readlines()
        with open(job_script_name, "w") as file:
            for line in lines:
                if line.startswith("START="):
                    file.write(f"START={start}\n")
                elif line.startswith("END="):
                    file.write(f"END={order}\n")
                elif line.startswith("NDIGIT="):
                    file.write(f"NDIGIT={ndigit}\n")
                elif line.startswith("srun"):
                    if is_gamma:
                        file.write("srun --mpi=pmi2 vasp_gam\n")
                    else:
                        file.write("srun --mpi=pmi2 vasp_std\n")
                else:
                    file.write(line)

    os.chdir("..")
    print("\n--- SCF script finished ---")

def prepare_namd(parameters, namd_inp):
    """
    Prepares the directory and input files for a NAMD calculation.

    Args:
        dirname (str): The name of the directory to create for the calculation.
    """

    dirname= namd_inp.get('dirname', 'step5') 
    # --- 2. Create directory and copy files ---
    print(f"\n--- Setting up directory '{dirname}' ---")
    os.makedirs(dirname, exist_ok=True)
    
    method = parameters.get('simulation_method', 'DISH')
    if method not in ['DISH', 'FSSH']:
        print(f"Warning: Unknown simulation method '{method}'. Defaulting to 'DISH'.")
        method = 'DISH'
    print(f"Using simulation method: {method}")
    if method == 'DISH':
        # Copy main input file
        shutil.copy2(os.path.join(TEMPLATE_DIR, "NAMD/5_dishinp"), os.path.join(dirname, "inp"))
        # Copy scripts
        scripts_to_copy = ["input.py", "population.py", "Dephase.py"]
        for script in scripts_to_copy:
            shutil.copy(os.path.join(SCRIPTS_DIR, script), dirname)        
        print("Files copied successfully.")
        
        os.chdir(dirname)
        # modify population.py
        with open("../VBCB", "r") as f:
            cbindex = int(f.readline().split('=')[1].strip())
        nsample = namd_inp.get('nsample', 100)
        namdtime = parameters.get('simulation_time', 10000000)
        bmin = namd_inp.get('bmin', -1) + cbindex
        bmax = namd_inp.get('bmax', 0) + cbindex
        is_hole = namd_inp.get('is_hole', False)
        nsw = parameters.get('wavecar_steps', 500)
        with open("population.py", "r") as file:
            lines = file.readlines()
        with open("population.py", "w") as file:
            for line in lines:
                if line.startswith("NSAMPLE "):
                    file.write(f"NSAMPLE  = {nsample}\n")
                elif line.startswith("NAMDTIME "):
                    file.write(f"NAMDTIME = {namdtime}\n")
                elif line.startswith("is_hole "):
                    file.write(f"is_hole  = {is_hole}\n")
                else:
                    file.write(line)
        
        # generate inicon
        iniband = parameters.get('INIBAND', 0) + cbindex
        generate_inicon(count=nsample, iniband=iniband, min_value=2, max_value=nsw)

    elif method == 'FSSH':
        # Copy main input file
        shutil.copy2(os.path.join(TEMPLATE_DIR, "NAMD/5_fsshinp"), os.path.join(dirname, "inp"))
        # Copy scripts
        scripts_to_copy = ["input.py", "poen_fssh.py"]
        for script in scripts_to_copy:
            shutil.copy(os.path.join(SCRIPTS_DIR, script), dirname)        
        print("Files copied successfully.")
        
        os.chdir(dirname)
        # modify poen_fssh.py
        with open("../VBCB", "r") as f:
            cbindex = int(f.readline().split('=')[1].strip())
        nsample = namd_inp.get('nsample', 100)
        namdtime = parameters.get('simulation_time', 1000)
        bmin = namd_inp.get('bmin', 0) + cbindex
        bmax = namd_inp.get('bmax', 10) + cbindex
        is_hole = namd_inp.get('is_hole', False)
        nsw = parameters.get('wavecar_steps', 500)
        with open("poen_fssh.py", "r") as file:
            lines = file.readlines()
        with open("poen_fssh.py", "w") as file:
            for line in lines:
                if line.startswith("nsw "):
                    file.write(f"nsw     = {nsw}\n")
                elif line.startswith("namdTime "):
                    file.write(f"namdTime = {namdtime}\n")
                elif line.startswith("bmin "):
                    file.write(f"bmin     = {bmin}\n")
                elif line.startswith("bmax "):
                    file.write(f"bmax     = {bmax}\n")
                else:
                    file.write(line)

        # generate inicon
        iniband = parameters.get('INIBAND', 10) + cbindex
        generate_inicon(count=nsample, iniband=iniband, min_value=2, max_value=nsw-namdtime)

    # --- 3. Create COUPCAR, modify input.py, inp and namd_sub ---
    print("\n--- Finalizing input files ---")
    # Create an empty COUPCAR file
    with open("COUPCAR", "w") as f:
        pass
    
    # Modify input.py
    bmax_stored = bmax + 10
    bmin_stored = bmin - 10
    with open("../KPOINTS", "r") as file:
        lines = file.readlines()
        # 提取第 4 行并解析 kx, ky, kz
        kx, ky, kz = map(int, lines[3].split())
        
        # 计算 kx, ky, kz 的乘积
    kpoints_product = kx * ky * kz
    is_gamma = (kpoints_product == 1)

    with open("input.py", "r") as file:
        lines = file.readlines()
    with open("input.py", "w") as file:
        for line in lines:
            if line.startswith("bmin_stored "):
                file.write(f"bmin_stored    = {bmin_stored}\n")
            elif line.startswith("bmax_stored "):
                file.write(f"bmax_stored    = {bmax_stored}\n")
            elif line.startswith("is_gamma_version "):
                file.write(f"is_gamma_version  = {is_gamma}\n")
            elif line.startswith("bmin "):
                file.write(f"bmin    = {bmin}\n")
            elif line.startswith("bmax "):
                file.write(f"bmax    = {bmax}\n")
            elif line.startswith("T_end "):
                file.write(f"T_end   = {nsw}\n")
            else:
                file.write(line)

    # Modify inp
    with open("inp", "r") as file:
        lines = file.readlines()
    with open("inp", "w") as file:
        for line in lines:
            if line.startswith("BMIN "):
                file.write(f"BMIN       = {bmin}\n")
            elif line.startswith("BMAX "):
                file.write(f"BMAX       = {bmax}\n")
            elif line.startswith("NAMDTIME "):
                file.write(f"NAMDTIME   = {namdtime}\n")
            elif line.startswith("NSAMPLE "):
                file.write(f"NSAMPLE    = {nsample}\n")
            elif line.startswith("NSW "):
                file.write(f"NSW        = {nsw-1}\n")
            elif line.startswith("LHOLE "):
                file.write(f"LHOLE      = {is_hole}\n")
            else:
                file.write(line)
    
    # Modify namd_sub
    slurm_path = os.path.join(SCRIPTS_DIR, "namd_sub")
    with open(slurm_path, "r") as file:
        lines = file.readlines()
    with open(slurm_path, "w") as file:
        for line in lines:
            if line.startswith("BMIN="):
                file.write(f"BMIN={bmin}\n")
            elif line.startswith("BMAX="):
                file.write(f"BMAX={bmax}\n")
            elif line.startswith("METHOD="):
                file.write(f"METHOD={method}\n")
            else:
                file.write(line)

    os.chdir('..')
    print(f"\n--- NAMD setup finished. Files are in '{dirname}' directory. ---")