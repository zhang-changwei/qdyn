# qdyn

qdyn is a toolkit for non-adiabatic quasiparticle dynamics in solids. It
combines simulation workflow orchestration, cluster execution, post-processing,
and a web UI for submitting and tracking tasks.

## Features

The recommended deployment is to run the qdyn frontend and backend on a
supercomputer login node.

```text
~~~~~~~~~~~~        ------------------------------
|          |        |       qdyn       |         |
|   User   | -----> | Frontend/Backend | Workers |
|          |        |    login node    |         |
~~~~~~~~~~~~        ------------------------------
   Browser                   Linux cluster
```

qdyn can also be deployed on a separate machine, connecting to computational resources with SSH.

```text
~~~~~~~~~~~~        --------------------        ~~~~~~~~~~~
|          |        |       qdyn       |  SSH   |         |
|   User   | -----> | Frontend/Backend | -----> | Workers |
|          |        |                  |        |         |
~~~~~~~~~~~~        --------------------        ~~~~~~~~~~~
   Browser           Windows/Mac/Linux         Linux cluster
```

|  | Workflow | Highlights | Dependencies | Refs |
| --- | --- | --- | --- | --- |
| 1 | NAMD with VASP | Standard NAMD workflow for solids | [`VASP`](https://www.vasp.at/) | - |
| 2 | NAMD with VASP + CA | Improved accuracy for transition metals | `vasp_ae`* | [1] |
| 3 | N<sup>2</sup>AMD with OpenMX | Efficient neural-network-assisted NAMD | [`OpenMX>=3.9`](https://www.openmx-square.org/), [`openmx-postprocess`](https://github.com/zhang-changwei/openmx-postprocess); build with `--extra ml --extra openmx` | [2] |
| 4 | N<sup>2</sup>AMD with OpenMX + ELPA | Optimized performance for larger systems | Same as workflow 3, plus [`ELPA`](https://elpa.mpcdf.mpg.de/) and [`qdyn-eigh-elpa`](https://github.com/zhang-changwei/qdyn-eigh-elpa) | - |

qdyn also provides:

- A browser-based interface for submitting and monitoring tasks.
- Persistent task storage backed by local and MongoDB databases.
- Selective dynamics support.
- Inference with pretrained MLFF and HamGNN models.
- Optional GPU acceleration for supported parts of the workflow.

> All workflows also depend on [`hfnamd`](https://github.com/zhang-changwei/Hefei-NAMD-DEV) for efficient NAMD simulation.

> `vasp_ae`: contact Professor Weibin Chu (wbchu@fudan.edu.cn) for access to the latest version.

## Prerequisites

- Worker nodes: Linux with a Slurm or PBS scheduler, `glibc >= 2.17`, and
  CUDA `>= 12.4` for GPU-enabled ML workflows.
- Backend server: MongoDB's `mongod` executable available on `PATH`. A
  self-managed MongoDB Community Server can be downloaded from
  [mongodb.com](https://www.mongodb.com/products/self-managed/community-edition).
- Frontend tooling: Node.js and npm.

## Install

### Backend

Install the full backend with ML and OpenMX support:

```bash
uv sync --extra ml --extra openmx --no-dev
export PYTHONPATH=$PWD/src:$PYTHONPATH
```

For a minimal backend without heavy ML dependencies such as PyTorch, use:

```bash
uv sync --no-dev
export PYTHONPATH=$PWD/src:$PYTHONPATH
```

> Note: OpenMX support builds a native extension, so the target machine must provide a working C compiler and a CMake-compatible build toolchain.

### Frontend

```bash
cd frontend
npm install
npm run build
cd ..
```

The production build is written to `frontend/dist/` and served by FastAPI in
production mode.

## Usage

1. Copy the example configuration files:

   ```bash
   cd config
   cp qdyn.yaml.example qdyn.yaml
   cp jf_base.yaml.example jf_base.yaml
   cd ..
   ```

2. Edit `config/qdyn.yaml` and `config/jf_base.yaml` for your cluster,
   scheduler, software modules, paths, and active worker pool.

3. Start MongoDB:

   ```bash
   python main.py --mongod
   ```

4. Generate the complete jobflow-remote project configuration:

   ```bash
   python src/scripts/generate_jf_config.py
   ```

5. Optional: download pretrained MLFF models on the worker environment. Models
   are stored under `~/.qdyn/pretrained/`.

   ```bash
   python src/scripts/download_pretrained_models.py --list-models
   python src/scripts/download_pretrained_models.py --nequip-model mir-group/NequIP-OAM-L --nequip-device cpu
   python src/scripts/download_pretrained_models.py --mace-model small
   ```

   Download the pretrained HamGNN model from [sci-ai.cn](https://sci-ai.cn) and
   place `universal2.0.ckpt` under `~/.qdyn/pretrained/`.

6. Start the jobflow runner:

   ```bash
   python main.py --jf
   ```

7. Start the backend server:

   ```bash
   uv run python main.py --server --port 8001
   ```

8. Start the frontend development server:

   ```bash
   cd frontend
   VITE_API_PORT=8001 npx vite --host 0.0.0.0
   ```


## Configuration

The example files in `config/` document the available settings:

- `qdyn.yaml.example` defines qdyn runtime settings, worker pools, scheduler
  resources, software modules, environment variables, and authentication.
- `jf_base.yaml.example` defines the shared jobflow-remote project, MongoDB
  queue, job store, and runner settings.

After changing worker pools or jobflow settings, rerun:

```bash
python src/scripts/generate_jf_config.py
```

## Roadmap

- Support for pseudo hydrogen.
- Support for the N<sup>2</sup>AMD-k workflow.
- Support for on-the-fly N<sup>2</sup>AMD workflows.

## Contributing

Pull requests and issues are welcome. See `CONTRIBUTING.md` for coding style,
docstring rules, and commit conventions.

## References

1. Chu, W. & Prezhdo, O. V. Concentric Approximation for Fast and Accurate
   Numerical Evaluation of Nonadiabatic Coupling with Projector Augmented-Wave
   Pseudopotentials. J. Phys. Chem. Lett. 12, 3082-3089 (2021).

2. Zhang, C. et al. Advancing nonadiabatic molecular dynamics simulations in
   solids with E(3) equivariant deep neural hamiltonians. Nat Commun 16, 2033
   (2025).
