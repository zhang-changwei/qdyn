import ast
import operator
import os
from pathlib import Path
from ase import Atoms
import ase.io
from typing import Any

from .params import TRAJ_FNAME_MAPPING, TRAJ_FORMAT_MAPPING

def write_strus(software: str, structures: list[Atoms], out_dir: str = '.') -> str:
    """Write structures to a trajectory file in software-native format.

    Args:
        software: Software name ('vasp', 'cp2k', etc.).
        structures: List of ASE Atoms objects to write.
        out_dir: Directory to write the trajectory file into. Default is
            current directory.

    Returns:
        Path to the written trajectory file.
    """
    track_name = TRAJ_FNAME_MAPPING.get(software)
    if track_name is None:
        raise ValueError(f"Unsupported software: {software}")
    ase_format = TRAJ_FORMAT_MAPPING.get(software)
    if ase_format is None:
        raise ValueError(f"Unsupported software: {software}")
    track_file = os.path.join(out_dir, track_name)
    ase.io.write(track_file, structures, format=ase_format)
    return track_file


def read_strus(
    stru_format: str,
    out_dir: str = '.',
    traj_path: str | None = None,
) -> list[Atoms]:
    """Read structures from trajectory file.

    Args:
        stru_format: Trajectory format alias or ASE format string
            (e.g. 'vasp-xdatcar', 'extxyz', 'lammps-data').
        out_dir: Directory containing the trajectory file (used when
            traj_path is None).
        traj_path: Explicit path to the trajectory file. If given,
            directory is ignored.

    Returns:
        List of ASE Atoms objects representing the structures.
    """
    if traj_path is None:
        track_name = TRAJ_FNAME_MAPPING.get(stru_format)
        if track_name is None:
            raise ValueError(
                f"Cannot infer trajectory filename from stru_format '{stru_format}'. "
                "Please provide traj_path explicitly."
            )
        traj_path = os.path.join(out_dir, track_name)
    return ase.io.read(traj_path, format=stru_format, index=':')


def write_stru(software: str, structure: Atoms, out_dir: str | Path) -> None:
    """Write ASE Atoms object to a structure file.

    Args:
        software: Software name ('vasp', 'cp2k', etc.).
        structure: ASE Atoms object to write.
        out_dir: Path to output structure file.
    """
    if software == 'vasp':
        ase.io.write(
            os.path.join(out_dir, "POSCAR"), structure, vasp5=True, direct=True
        )
    else:
        raise ValueError(f"Unsupported software: {software}")

# TODO: unable to handle injections like "10vbm"
def safe_eval(expr: str) -> Any:
    ALLOWED_OPS = {ast.Add: operator.add, ast.Sub: operator.sub}
    tree = ast.parse(expr, mode='eval')

    def _eval(node):
        if isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_OPS:
            return ALLOWED_OPS[type(node.op)](_eval(node.left), _eval(node.right))
        else:
            raise ValueError(f"Unsupported expression: {expr}")

    return _eval(tree.body)

def parse_band_index(
    expr: str, 
    vbm: int,
    nbands: int,
) -> int:
    """1-based"""
    expr = expr.lower()

    expr = expr.replace("vbm", str(vbm))
    expr = expr.replace("homo", str(vbm))
    expr = expr.replace("cbm", str(vbm + 1))
    expr = expr.replace("lumo", str(vbm + 1))
    
    band = safe_eval(expr)

    # validate band <= nbands
    band = 1 if band < 1 else band
    band = nbands if band > nbands else band

    return band
