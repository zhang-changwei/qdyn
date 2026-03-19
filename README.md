# qdyn
A toolkit for non-adiabatic quasiparticle dynamics

# Install

```bash
# production environment (w/ N2AMD)
uv sync --extra ml --no-dev
# production environment (w/o N2AMD)
uv sync --no-dev
# development environment (w/ N2AMD)
uv sync --extra ml
# development environment (w/o N2AMD)
uv sync
```

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