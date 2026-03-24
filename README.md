# qdyn
A toolkit for non-adiabatic quasiparticle dynamics

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
4. Start jf `python main.py --jf`  

export PYTHONPATH=$HOME/src/qdyn/src:$PYTHONPATH
export JFREMOTE_PROJECTS_FOLDER=/data/home/cwzhang/src/qdyn/jf_config
export JFREMOTE_PROJECT=jf_qdyn

* Check MongoDB / Jobflow status
`ps -u cwzhang -o pid,cmd | grep mongo`
`jf project list -w`
`jf runner status`
`jf runner info`

# How to contribute

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