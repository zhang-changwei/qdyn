# QDYN - 非绝热准粒子动力学工具包

## 项目概述

QDYN 是一个用于非绝热准粒子动力学模拟的 Python 工具包，支持 VASP、CP2K、SIESTA、ABACUS、OpenMX 等第一性原理计算软件。项目基于 FastAPI 提供 Web 服务接口，使用 SLURM 进行作业调度管理，并通过 jobflow-remote 实现工作流编排。

## 技术栈

- **Python**: >= 3.12
- **Web 框架**: FastAPI + Uvicorn
- **作业调度**: SLURM
- **工作流引擎**: jobflow + jobflow-remote
- **原子模拟**: ASE (Atomic Simulation Environment)
- **材料计算**: pymatgen (INCAR 解析)
- **包管理**: uv

## 项目结构

```
qdyn/
├── main.py                 # 程序入口，支持 CLI 和服务器模式
├── config/
│   └── qdyn.yaml           # 主配置文件
├── src/
│   ├── __init__.py
│   ├── input.py            # Pydantic 输入模型定义
│   ├── input_prepare.py    # VASP 输入文件准备 (POSCAR/KPOINTS/POTCAR/INCAR)
│   ├── job_manager.py      # FastAPI 服务器 + SLURM 作业管理
│   ├── main_workflow.py    # 主工作流逻辑
│   ├── params.py           # 默认参数模板 (sr/nvt/nve/scf)
│   ├── output_postprocess.py # 输出后处理 (MD 数据提取)
│   └── tools/
│       ├── canac.py        # 本征值和 NAC 提取
│       ├── dephase.py      # 退相位时间计算
│       ├── nvt.py          # NVT 分子动力学运行
│       ├── run_vasp.py     # VASP 运行封装
│       ├── prepare_namd.py # NAMD 预处理
│       └── libcanac/       # CANAC 核心库
│           ├── abacuswfc.py
│           ├── aeolap.py
│           ├── cp2kwfc.py
│           ├── hamgnnhugewfc.py
│           ├── hamnetwfc.py
│           ├── mod_hungarian.py
│           ├── siestawfc.py
│           └── utils.py
└── namd_server_test/       # 旧版 VASP 工作流代码 (仅供参考)
```

**注意**: `namd_server_test/` 目录包含旧版 VASP 工作流的实现代码，采用不同的架构设计，但各 step 的具体处理逻辑可作为参考。

**重要**: `src/constants.py` 文件不存在，但 `job_manager.py` 导入了 `JOB_MANAGER_POLL_INTERVAL`，需要创建此文件并定义该常量。

## 核心模块说明

### params.py
- **params_default**: 默认参数模板字典
  - `sr.vasp`: 结构优化默认参数 (NELM=90, NSW=100, IBRION=2, ISIF=2 等)
  - `nvt.vasp`: NVT 分子动力学默认参数 (ALGO=Normal, NSW=1000, POTIM=1, SMASS=0 等)
  - `nve.vasp`: NVE 分子动力学默认参数 (SMASS=-3, NSW=5000 等)
  - `scf.vasp`: SCF 计算默认参数 (LORBIT=11, NEDOS=2001 等)
- **_incar**: 基础 INCAR 参数 (ISTART=0, ISPIN=1, PREC=Accurate 等)

### job_manager.py
- **SlurmManager**: SLURM 作业调度管理器
  - 自动轮询作业状态 (间隔由 `constants.JOB_MANAGER_POLL_INTERVAL` 定义)
  - 作业提交和状态追踪
  - 任务配额管理
  - 自动生成 SLURM 批处理脚本
- **FastAPI 端点**:
  - `POST /tasks` - 创建任务
  - `GET /tasks` - 列出所有任务
  - `DELETE /tasks/{task_id}` - 删除任务
  - `POST /jobs` - 注册作业
  - `GET /jobs` - 列出所有作业
  - `GET /jobs/{job_uuid}` - 获取作业详情

### main_workflow.py
- **MainWorkflow**: 主工作流类
  - 加载配置文件
  - 根据 `steps` 参数执行 NVT/NVE/SCF/PRE_NAMD/NAMD 步骤
  - 与 jobflow-remote 集成提交作业到 `local_slurm` worker
  - **步骤顺序验证**: NAMD 方法要求步骤连续 (nvt → nve → scf → pre_namd → namd)
  - **断点续算**: 支持 `resume` 参数从之前任务继续
- **已导入的功能**:
  - `run_nvt()`: NVT 分子动力学 (从 tools.nvt 导入)
  - `run_pre_namd()`: NAMD 预处理 (从 tools.prepare_namd 导入)
- **待完成功能**:
  - `run_nve()`: NVE 分子动力学 (在 main_workflow.py 中引用但未导入)
  - `run_scf()`: SCF 计算 (在 main_workflow.py 中引用但未导入)

### input_prepare.py
- **VASP 输入准备函数**:
  - `prepare_vasp_inputs()`: 统一准备 POSCAR、KPOINTS、POTCAR、INCAR
  - `prepare_poscar()`: 通过 ASE 写入 POSCAR 结构文件
  - `prepare_kpoints()`: 根据 kspacing 生成 KPOINTS (Gamma 点网格)
  - `prepare_potcar()`: 拼接赝势文件 (支持多种命名格式)
  - `prepare_incar()`: 使用 pymatgen Incar 类生成 INCAR

- **参数优先级**: `params_default` → 传入参数 → `incar_params` 字符串

### input.py
- **基础输入模型**:
  - `BasicInputT`: 软件选择 (`vasp`/`cp2k`/`siesta`/`abacus`/`openmx`)、绘图开关
  - `SchedulerConfigT`: 调度器配置 (保留用于未来扩展)
  - `BasicCalInputT`: 基础计算输入 (kspacing, encut, ncore, kpar, parameters)

- **步骤输入模型** (每个模型包含 `to_vasp_incar()` 方法):
  - `SRInputT`: 结构优化参数 (继承 BasicCalInputT, nsw, ibrion, isif, ediffg 等)
  - `NVTInputT`: NVT 分子动力学参数 (kspacing, md_thermostat, md_dt, md_step, temp_begin, temp_end 等)
  - `NVEInputT`: NVE 分子动力学参数 (继承 BasicCalInputT, smass=-3, potim, nsw 等)
  - `SCFInputT`: 静态 SCF 计算参数 (继承 BasicCalInputT, lorbit, nelm 等)
  - `PreNAMDInputT`: NAMD 预处理参数 (bmin, bmax, md_dt, adiabatic_rep, surface_hopping, adv)

- **主输入模型**:
  - `InputT`: 主输入模型，包含 basic_input, scheduler_config, nvt_input, nve_input, scf_input, prenamd_input, steps

- **工具函数**:
  - `grep_input_parameters()`: 从文本文件提取参数 (格式: `key = value1 value2 ...`)
  - `_parse_value_string()`: 解析参数值字符串
  - `_parse_single_value()`: 解析单个值 (自动转换 bool/int/float/str)

### output_postprocess.py
- **VASP 输出处理**:
  - `extract_md_data_from_oszicar()`: 从 OSZICAR 提取 MD 数据
    - 返回统一格式的字典: steps, temperatures, total_energies, potential_energies, kinetic_energies, converged, potim
    - 自动检测 SCF 收敛状态

### tools/nvt.py
- **run_nvt()**: NVT 分子动力学主函数 (`@job` 装饰器)
  - **自动重试机制**: 如果温度未收敛（偏差 > 目标温度 10%），自动读取 CONTCAR 重新开始
  - **最大重试次数**: `MAX_NVT_RETRIES = 10`
  - **收敛检查 1**: SCF 收敛性检查，不收敛则直接报错
  - **收敛检查 2**: 温度收敛性检查，不收敛则重试
  - **文件备份**: 每轮计算文件备份到 `nvt_attempt_{n}/` 目录
- **_prepare_nvt_input()**: 准备 NVT 输入文件
  - 支持 `md_thermostat`: `nhc` (Nose-Hoover) 或 `rescale_v` (速度重标定)
- **_process_nvt_output()**: 处理 VASP 输出，返回收敛状态
- **check_scf_convergence()**: 检查 SCF 收敛性 (通用函数)
- **check_temperature_convergence()**: 检查温度收敛性 (通用函数)
- **plot_nvt_results()**: 绘制 NVT 结果图 (温度、势能、总能量)
- **save_md_data()**: 保存 MD 数据到统一格式文件

### tools/run_vasp.py
- **run_vasp()**: VASP 运行封装
  - 自动检测 K 点数选择 `vasp_gam` 或 `vasp_std`
  - 支持 `is_alle` 参数使用全电子 VASP (`vasp_ae`)
  - 使用 `mpirun -np` 启动并行计算

### tools/prepare_namd.py
- **run_pre_namd()**: NAMD 预处理主函数 (`@job` 装饰器)
  - 调用 `extract_eigvals_and_nacs()` 提取本征值和 NAC
  - 支持 DISH 表面跳跃方法时计算退相位时间
  - 返回 EIGTXT, NATXT, DEPHTIME 文件路径
- **sample_initial_conditions()**: 生成初始条件采样

### tools/dephase.py
- **calculate_dephasing_time()**: 计算退相位时间 (`@job` 装饰器)
  - 读取 `EIGTXT` 能量文件
  - 计算 ACF、退相位函数 D(t)
  - 通过高斯拟合提取退相位时间
  - 输出 `DEPHTIME` 矩阵文件
- **dephase()**: 核心 ACF 和退相位函数计算
  - 公式: D(t) = exp(-G(t)), G(t) = (1/ℏ²)∫∫C(t)dt₁dt₂
  - 返回: ACF, D(t), 声子影响谱 I(ω)

### tools/canac.py
- **extract_eigvals_and_nacs()**: 提取本征值和非绝热耦合
  - 支持多种软件 (VASP/CP2K/SIESTA/ABACUS/OPENMX/HAMGNN)
  - 使用多进程并行计算时间重叠矩阵
  - 版本: CA-NAC 1.2.0_beta
- **calc_tdolap_wrapper()**: 时间重叠矩阵计算包装器
  - 支持断点续算
  - 读取波函数文件并计算本征值

### tools/libcanac/
- CANAC 核心库模块
  - `aeolap.py`: AEOLAP 核心算法
  - `utils.py`: 工具函数 (load_wfc, close_wfc, calc_tdolap)
  - `vaspwfc.py`: VASP 波函数处理
  - `abacuswfc.py`: ABACUS 波函数处理
  - `cp2kwfc.py`: CP2K 波函数处理
  - `siestawfc.py`: SIESTA 波函数处理
  - `hamnetwfc.py`: HamNet 波函数处理
  - `hamgnnhugewfc.py`: HamGNN Huge 波函数处理
  - `mod_hungarian.py`: 匈牙利算法实现

## 配置文件 (config/qdyn.yaml)

```yaml
basic:
  workflow_poll_interval: 10    # 工作流轮询间隔 (秒)

machine:
  partition: queue1-1           # SLURM 分区名称
  cpus_per_node: 64             # 每节点 CPU 核心数
  working_dir: /path/to/work    # 工作目录 (必需)

module: 
  vasp: ['compiler/intel/2021.3.0', 'mpi/intelmpi/2021.3.0']
  python: []

export: 
  vasp:
    PATH: '/path/to/bin'
    LD_LIBRARY_PATH: '/path/to/lib'
  python:
    PATH: '/path/to/bin'

pp_path:
  vasp: ''                      # 赝势路径

orb_path:
  vasp: ''                      # 轨道文件路径
  
nvt:
  vasp:
    nodes: 2
    ntasks_per_node: 64
    cpus_per_task: 1

nve:
  vasp:
    nodes: 2
    ntasks_per_node: 64
    cpus_per_task: 1

scf:
  vasp:
    nodes: 2
    ntasks_per_node: 64
    cpus_per_task: 1
```

**配置文件查找顺序**:
1. `--config` 命令行参数指定的路径
2. `QDYN_CONFIG` 环境变量
3. 默认路径 `config/qdyn.yaml`

## 常用命令

### 安装依赖
```bash
uv sync
```

### 启动作业管理服务器
```bash
# 使用默认配置路径 (config/qdyn.yaml)
python main.py --server

# 指定配置文件路径
python main.py --server --config /path/to/qdyn.yaml

# 或使用环境变量
QDYN_CONFIG=/path/to/qdyn.yaml python main.py --server
```

### 本地运行
```bash
python main.py
```

## 开发指南

### 代码风格
- 使用 Pydantic 进行数据验证和模型定义
- 使用 `@job` 装饰器标记可作业化的函数 (jobflow)
- 配置文件使用 YAML 格式
- 日志使用 Python 标准 logging 模块
- 使用 pymatgen 的 Incar 类处理 INCAR 文件

### 添加新软件支持
1. 在 `input.py` 的 `Literal` 类型中添加软件名称
2. 在 `config/qdyn.yaml` 中添加软件配置 (module, export, pp_path, orb_path, nvt, nve)
3. 在 `input_prepare.py` 中添加 `prepare_{software}_inputs()` 函数
4. 在 `tools/nvt.py` 中添加 `_prepare_nvt_input_{software}()` 函数
5. 在 `params.py` 中添加默认参数模板
6. 在 `tools/libcanac/` 中添加波函数处理模块

### Git 工作流
```bash
# 克隆仓库
git clone https://github.com/zhang-changwei/qdyn.git

# 创建本地分支
git branch local
git checkout local

# 完成修改后...
git checkout main
git pull
git merge local
git push
```

## 依赖说明

| 包名 | 用途 |
|------|------|
| fastapi | Web API 框架 |
| uvicorn | ASGI 服务器 |
| ase | 原子模拟环境 |
| pymatgen | 材料计算工具 (INCAR 解析) |
| jobflow | 工作流定义 |
| jobflow-remote | 远程作业执行 |
| jupyter | 交互式开发 |
| natsort | 自然排序 (canac.py 使用) |

**注意**: `scipy` 在 `dephase.py` 中使用，但未在 pyproject.toml 中声明。

## 实现状态

| 模块 | 状态 |
|------|------|
| job_manager.py | ⚠️ 已实现 (需创建 constants.py) |
| main_workflow.py | ⚠️ 部分实现 (缺少 run_nve, run_scf 导入) |
| input_prepare.py | ✅ VASP 已实现 |
| params.py | ✅ 已实现 |
| output_postprocess.py | ✅ 已实现 |
| tools/nvt.py | ⚠️ 已实现 (is_alle 参数未定义) |
| tools/run_vasp.py | ✅ 已实现 |
| tools/prepare_namd.py | ✅ 已实现 |
| tools/dephase.py | ⚠️ 已实现 (缺少 scipy 依赖声明) |
| tools/canac.py | ⚠️ 部分实现 (VASP/SIESTA/HAMGNN/ABACUS 支持，is_alle 未实现) |
| tools/libcanac/ | ✅ 已实现 |

## 待解决问题

1. **缺少 constants.py**: `job_manager.py` 导入 `JOB_MANAGER_POLL_INTERVAL` 但文件不存在
2. **缺少 run_nve/run_scf 导入**: `main_workflow.py` 中引用但未导入这些函数
3. **scipy 依赖**: `dephase.py` 使用 scipy 但未在 pyproject.toml 中声明
4. **scf 配置**: `main_workflow.py` 中使用 `self.config['scf']` 但配置文件中未定义
5. **working_dir 配置**: `job_manager.py` 中使用 `self.config['machine']['working_dir']` 但配置文件中未定义
6. **is_alle 参数**: `NVTInputT` 中未定义 `is_alle` 属性，但 `run_nvt` 中使用了 `parameters.is_alle`；同时 `canac.py` 中 `assert is_alle is False` 表示该功能尚未实现

## 注意事项

1. **配置文件必需**: 服务器启动时需要有效的 `qdyn.yaml` 配置文件
2. **SLURM 环境**: 作业提交功能依赖 SLURM 调度系统 (sbatch, sacct 命令)
3. **模块加载**: 配置中的 module 和 export 用于在作业脚本中加载计算软件环境
4. **参数来源**: 默认参数从 `params.py` 加载，可与用户参数合并