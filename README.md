# qdyn
A toolkit for non-adiabatic quasiparticle dynamics

## Optional OpenMX postprocess extension

The OpenMX postprocess reader is shipped as an optional subpackage built with
CMake. It is not installed by default.

To install QDYN with the optional ML/OpenMX extras:

```bash
uv sync --extra ml
```

This installs `qdyn-openmx-postprocess` and builds the native extension during
package installation. A working C compiler and CMake-compatible build toolchain
must be available on the target machine.

# Install

```bash
uv venv --python 3.12
# production environment (w/ N2AMD)
uv sync --extra ml --no-dev
# production environment (w/o N2AMD)
uv sync --no-dev
# development environment (w/ N2AMD)
uv sync --extra ml
# development environment (w/o N2AMD)
uv sync
```

# Usage

1. Modify `config/qdyn.yaml`
2. Start mongod `python main.py --mongod`
3. Generate jf project configuration `jf project generate jf_qdyn`
4. Download pretrained ML models on worker if needed
   Models are saved under `~/.qdyn/pretrained/`.
   ```bash
   python src/scripts/download_pretrained_models.py --list-models
   python src/scripts/download_pretrained_models.py --nequip-model mir-group/NequIP-OAM-L --nequip-device cpu
   python src/scripts/download_pretrained_models.py --mace-model small
   ```
5. Start jf `python main.py --jf`  

```
export PYTHONPATH=$HOME/src/qdyn/src:$PYTHONPATH
export JFREMOTE_PROJECTS_FOLDER=$HOME/src/qdyn/config
export JFREMOTE_PROJECT=jf_qdyn
```

* Check MongoDB / Jobflow status
```
ps -u cwzhang -o pid,cmd | grep mongo
jf project list -w
jf runner status
jf runner info
jf job list
```

# How to contribute

See `CONTRIBUTING.md` for coding style, docstring rules, and commit conventions.

```bash
# clone the repo
git clone https://github.com/zhang-changwei/qdyn.git
# create a local branch
git branch local
git checkout local
# Do your changes in this branch
# ...
# Before push to Github, pull the latest updates
git checkout main
git pull
# Merge your local branch and handle the conflicts
git merge local
# Finally push
git push
```

# Frontend

## Start backend server

```bash
PYTHONPATH=src uv run python main.py --server --port 8001
```

## Start frontend dev server

```bash
cd frontend && npm install
VITE_API_PORT=8001 npx vite --host 0.0.0.0
```

## Build for production

```bash
cd frontend && npm run build
```

The built assets will be in `frontend/dist/`, served by FastAPI at static file hosting in production mode.

## Fetch the submodule
```bash
git submodule update --init --recursive
```
