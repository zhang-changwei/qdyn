# QDYN - 非绝热准粒子动力学工具包

## 项目概述

QDYN 是一个用于非绝热准粒子动力学模拟的 Python 工具包，支持 VASP、CP2K、SIESTA、ABACUS、OpenMX 等第一性原理计算软件。项目基于 FastAPI 提供 Web 服务接口，使用 SLURM 进行作业调度管理，并通过 jobflow-remote 实现工作流编排。

## 技术栈

- **Python**: >= 3.12
- **Web 框架**: FastAPI + Uvicorn
- **作业调度**: SLURM
- **工作流引擎**: jobflow + jobflow-remote
- **原子模拟**: ASE (Atomic Simulation Environment)
- **包管理**: uv

## 项目结构

```
qdyn/
├── main.py                 # 程序入口，支持 CLI 和服务器模式
├── config/
│   └── qdyn.yaml           # 主配置文件
├── src/
│   ├── __init__.py
│   ├── constants.py        # 全局常量定义 (轮询间隔等)
│   ├── input.py            # Pydantic 输入模型定义
│   ├── output.py           # 输出数据结构
│   ├── job_initialize.py   # 作业初始化逻辑 (结构文件、势函数准备)
│   ├── job_manager.py      # FastAPI 服务器 + SLURM 作业管理
│   ├── main_workflow.py    # 主工作流逻辑
│   └── tools/
│       ├── canac.py        # 本征值和 NAC 提取 (待实现)
│       ├── dephase.py      # 退相位时间计算
│       └── nvt.py          # NVT 分子动力学运行
└── namd_server_test/       # 旧版 VASP 工作流代码 (仅供参考)
```

**注意**: `namd_server_test/` 目录包含旧版 VASP 工作流的实现代码，采用不同的架构设计，但各 step 的具体处理逻辑可作为参考。

## 核心模块说明

### job_manager.py
- **SlurmManager**: SLURM 作业调度管理器
  - 自动轮询作业状态 (间隔由 `constants.JOB_MANAGER_POLL_INTERVAL` 定义，默认 30 秒)
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
  - 根据 `steps` 参数执行 NVT/NVE 分子动力学步骤
  - 与 jobflow-remote 集成提交作业到 `local_slurm` worker

### job_initialize.py
- **job_initialize()**: 作业初始化函数
  - 读取结构文件 (通过 ASE)
  - 根据软件类型准备输入文件 (目前支持 VASP)
  - 输入文件直接写入当前目录 (jobflow 自动管理工作目录)

- **VASP 输入准备函数**:
  - `prepare_vasp_inputs()`: 统一准备 POSCAR、KPOINTS、POTCAR、INCAR
  - `prepare_poscar()`: 写入 POSCAR 结构文件
  - `prepare_kpoints()`: 根据 kspacing 生成 KPOINTS
  - `prepare_potcar()`: 拼接赝势文件
  - `prepare_incar()`: 生成 INCAR (参数优先级: base → step_input.to_vasp_incar() → incar_params → parameters string)

- **INCAR 工具函数**:
  - `write_incar()`: 写入 INCAR 文件
  - `format_incar_value()`: 格式化值 (bool→.TRUE./.FALSE., list→空格分隔)
  - `parse_incar_string()`: 解析 KEY=VALUE 格式参数字符串
  - `parse_incar_value()`: 解析单个值到 Python 类型

### input.py
- **步骤输入模型** (每个模型包含默认参数和 `to_vasp_incar()` 方法):
  - `SRInputT`: 结构优化参数 (encut, kspacing, nsw, ibrion, isif, ediffg 等)
  - `NVTInputT`: NVT 分子动力学参数 (potim, nsw, temp_begin, temp_end, smass 等)
  - `NVEInputT`: NVE 分子动力学参数 (potim, nsw, smass=-3 等)
  - `SCFInputT`: 静态 SCF 计算参数 (lorbit, nedos 等)
  - 每个模型都有 `parameters: str` 字段用于额外参数 (KEY=VALUE 格式)

- **常量**:
  - `VASP_BASE_INCAR`: 基础 INCAR 参数 (ISTART, ISPIN, PREC, ISMEAR 等)

- **主输入模型**:
  - `InputT`: 主输入模型，包含 basic_input, scheduler_config, steps
  - `BasicInputT`: 软件选择、绘图开关

### tools/
- **nvt.py**: NVT 分子动力学运行 (`@job` 装饰器)
  - `run_nvt()`: 主函数，准备输入、运行 VASP、处理输出
    - **自动重试机制**: 如果温度未收敛（偏差 > 目标温度 10%），自动读取 CONTCAR 重新开始 NVT 计算
    - **最大重试次数**: `MAX_NVT_RETRIES = 10`，超过则抛出错误
    - **收敛检查 1**: SCF 收敛性检查，不收敛则直接报错
    - **收敛检查 2**: 温度收敛性检查，不收敛则重试
    - **文件备份**: 每轮计算文件备份到 `nvt_attempt_{n}/` 目录
  - `_prepare_nvt_input_vasp()`: 调用 prepare_vasp_inputs 准备输入文件
  - `_process_nvt_output_vasp()`: 处理输出，返回 (scf_converged, temp_converged, avg_temp, max_deviation)
  - `extract_md_data_from_oszicar()`: 从 OSZICAR 提取 MD 数据
  - `save_md_data()`: 保存 MD 数据到文件
  - `check_md_convergence()`: 检查 SCF 收敛性（检测 self-consistency 错误）
  - `plot_nvt_results()`: 绘制 NVT 结果图 (温度、势能、总能量)
- **dephase.py**: 计算退相位时间
  - 读取 `EIGTXT` 能量文件
  - 计算 ACF、退相位函数、声子影响谱
  - 支持绘图输出
- **canac.py**: 提取本征值和非绝热耦合 (NAC) - 待实现

### output.py
- **Output**: 输出数据结构
  - `stdout`: 标准输出行列表
  - `files`: 输出文件路径列表
  - `images`: 图像文件路径列表
  - `merge()`: 合并另一个 Output 对象

### constants.py
- `JOB_MANAGER_POLL_INTERVAL = 30`: 作业管理器轮询间隔 (秒)

## 配置文件 (config/qdyn.yaml)

```yaml
basic:
  workflow_poll_interval: 10    # 工作流轮询间隔 (秒)

machine:
  partition: queue1-1           # SLURM 分区名称
  cpus_per_node: 64             # 每节点 CPU 核心数
  working_dir: /path/to/work    # 作业工作目录 (必需)

module: 
  vasp: ['compiler/intel/2021.3.0', 'mpi/intelmpi/2021.3.0']

export: 
  vasp:
    PATH: '/path/to/bin'
    LD_LIBRARY_PATH: '/path/to/lib'

pp_path:
  vasp: ''                      # 赝势路径

orb_path:
  vasp: ''                      # 轨道文件路径
  
nvt:
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

### 添加新软件支持
1. 在 `input.py` 的 `Literal` 类型中添加软件名称
2. 在 `config/qdyn.yaml` 中添加软件配置 (module, export, pp_path, orb_path, nvt)
3. 在 `job_initialize.py` 中添加 `prepare_{software}_inputs()` 函数，实现输入文件准备逻辑
4. 在 `tools/nvt.py` 中添加 `_prepare_nvt_input_{software}()` 函数，调用步骤 3 中的函数

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
| jobflow | 工作流定义 |
| jobflow-remote | 远程作业执行 |
| jupyter | 交互式开发 |

## 实现状态

| 模块 | 状态 |
|------|------|
| job_manager.py | ✅ 已实现 |
| main_workflow.py | ✅ 基本实现 |
| job_initialize.py | ✅ VASP 已实现 |
| tools/nvt.py | ✅ VASP 已实现 |
| tools/dephase.py | ✅ 已实现 |
| tools/canac.py | ⏳ 待实现 |

## 注意事项

1. **配置文件必需**: 服务器启动时需要有效的 `qdyn.yaml` 配置文件
2. **SLURM 环境**: 作业提交功能依赖 SLURM 调度系统 (sbatch, sacct 命令)
3. **模块加载**: 配置中的 module 和 export 用于在作业脚本中加载计算软件环境
4. **working_dir**: 配置文件中的 `machine.working_dir` 必需，用于存放任务目录