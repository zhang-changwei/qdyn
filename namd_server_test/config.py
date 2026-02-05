import os

# 基础路径配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JOBS_DIR = os.path.join(BASE_DIR, 'jobs')
SCRIPTS_DIR = os.path.join(BASE_DIR, 'scripts')
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')

# 确保目录存在
os.makedirs(JOBS_DIR, exist_ok=True)

# Slurm脚本模板位置
SLURM_SCRIPTS = {
    'vasp_optimize': os.path.join(SCRIPTS_DIR, 'vasp_optimize.slurm'),
    'vasp_nvt': os.path.join(SCRIPTS_DIR, 'vasp_nvt.slurm'),
    'vasp_nve': os.path.join(SCRIPTS_DIR, 'vasp_nve.slurm'),
    'vasp_wavecar': os.path.join(SCRIPTS_DIR, 'vasp_wavecar.slurm'),
    'hefei_namd': os.path.join(SCRIPTS_DIR, 'hefei_namd.slurm')
}

# 后处理脚本位置
POSTPROCESS_SCRIPTS = {
    'check_optimization': os.path.join(SCRIPTS_DIR, 'check_optimization.py'),
    'check_nvt': os.path.join(SCRIPTS_DIR, 'check_nvt.py'),
    'extract_trajectory': os.path.join(SCRIPTS_DIR, 'extract_trajectory.py'),
    'check_wavecar': os.path.join(SCRIPTS_DIR, 'check_wavecar.py'),
    'analyze_namd': os.path.join(SCRIPTS_DIR, 'analyze_namd_results.py')
}

# 默认计算参数
DEFAULT_PARAMETERS = {
    'new_job': 'True',
    'force_recalculate': 'False',
    'temperature': 300,
    'nvt_steps': 1000,
    'nve_steps': 1000,
    'wavecar_steps': 500,
    'whichA': 'None', 
    'simulation_method': 'DISH',
    'INIBAND': 0,
    'simulation_time': 1000
}

NAMD_INP = {
    'dirname': 'step5',
    'bmin': 0, 
    'bmax': 8,
    'nsample': 50,
    'is_hole': False
}

SELECTIVE_PARAMETERS = {
    'INCAR': ['IVDW=11'],
    'namd_dir': 'step52'
}
