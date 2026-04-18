import ast
import operator
import os
from pathlib import Path
from ase import Atoms
import ase.io
from typing import Any

from .params import md_tracks, md_ase_formats

def write_strus(software: str, structures: list[Atoms], directory: str = '.') -> str:
    """Write structures to a trajectory file in software-native format.

    Args:
        software: Software name ('vasp', 'cp2k', etc.).
        structures: List of ASE Atoms objects to write.
        directory: Directory to write the trajectory file into. Default is
            current directory.

    Returns:
        Path to the written trajectory file.
    """
    track_name = md_tracks.get(software)
    if track_name is None:
        raise ValueError(f"Unsupported software: {software}")
    ase_format = md_ase_formats.get(software)
    if ase_format is None:
        raise ValueError(f"Unsupported software: {software}")
    track_file = os.path.join(directory, track_name)
    ase.io.write(track_file, structures, format=ase_format)
    return track_file


def read_strus(
    software: str,
    directory: str = '.',
    traj_file_path: str | None = None,
) -> list[Atoms]:
    """Read structures from trajectory file.

    Args:
        software: Software name ('vasp', 'cp2k', etc.).
        directory: Directory containing the trajectory file (used when
            traj_file_path is None).
        traj_file_path: Explicit path to the trajectory file. If given,
            directory is ignored.

    Returns:
        List of ASE Atoms objects representing the structures.
    """
    if traj_file_path is None:
        track_name = md_tracks.get(software)
        if track_name is None:
            raise ValueError(f"Unsupported software: {software}")
        traj_file_path = os.path.join(directory, track_name)
    ase_format = md_ase_formats.get(software)
    if ase_format is None:
        raise ValueError(f"Unsupported software: {software}")
    return ase.io.read(traj_file_path, format=ase_format, index=':')


def write_stru(software: str, structure: Atoms, output_path: os.PathLike):
    """Write ASE Atoms object to a structure file.

    Args:
        software: Software name ('vasp', 'cp2k', etc.).
        structure: ASE Atoms object to write.
        output_path: Path to output structure file.
    """
    if software == 'vasp':
        ase.io.write(
            os.path.join(output_path, "POSCAR"), structure, vasp5=True, direct=True
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
