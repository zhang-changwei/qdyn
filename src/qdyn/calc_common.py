import ast
import json
import operator
import os
import re
from pathlib import Path
from ase import Atoms
import ase.io
from typing import Any
import logging

from .input import InputT
from .pool import WorkerPool
from .params import TRAJ_FNAME_MAPPING, TRAJ_FORMAT_MAPPING

logger = logging.getLogger(__name__)

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


class TrajWriter:
    def __init__(self, dyn, atoms, fname='qdyn.extxyz', format='extxyz'):
        self.dyn = dyn
        self.atoms = atoms
        self.fname = fname
        self.format = format
        self.file = open(fname, 'w')
    
    def __call__(self):
        ase.io.write(self.file, self.atoms, append=True, format=self.format)

    def close(self):
        self.file.close()


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

_BAND_SYMBOL_RE = re.compile(r"\b(vbm|homo|cbm|lumo)\b")

def parse_band_index(
    expr: str,
    vbm: int,
    nbands: int,
) -> int:
    """1-based"""
    values = {"vbm": vbm, "homo": vbm, "cbm": vbm + 1, "lumo": vbm + 1}
    normalized = _BAND_SYMBOL_RE.sub(
        lambda m: str(values[m.group(1)]),
        expr.lower(),
    ).strip()

    band = safe_eval(normalized)

    # validate band <= nbands
    band = 1 if band < 1 else band
    band = nbands if band > nbands else band

    return band


def count_trajectory_frames(path: str, stru_format: str) -> int:
    """Count frames in a trajectory file without loading all atoms into memory.

    Uses format-specific lightweight scanning when available, falls back
    to ASE iread for unknown formats.

    Parameters
    ----------
    path : str
        Path to the trajectory file.
    stru_format : str
        ASE I/O format string (e.g. 'vasp-xdatcar').
    """
    if stru_format == "vasp-xdatcar":
        # Scan for "Direct configuration=" markers — O(n) read, no Atoms created
        with open(path, "r", encoding="utf-8", errors="replace") as fd:
            count = sum(1 for line in fd if "Direct configuration=" in line)
        # If no markers found but file is readable (e.g. single-frame POSCAR),
        # fall back to ASE to determine actual frame count
        if count > 0:
            return count

    # Generic fallback: may or may not be truly streaming depending on format.
    # TODO: add lightweight frame counters for other formats (e.g. xyz, cp2k)
    #       as they are supported, similar to the XDATCAR fast path above.
    from ase.io import iread
    return sum(1 for _ in iread(path, format=stru_format, index=":"))


def read_trajectory_summary(
    *,
    pool: WorkerPool,
    file_hash: str,
    formats: list[str],
) -> tuple[bool, dict[str, Any]]:
    """Read a best-effort trajectory summary from a remote pool file.

    Returns an empty dict when the file cannot be read or none of the provided
    ASE formats can parse it.

    Returns:
        tuple
        - exists (bool): Whether the file was successfully read and parsed.
        - summary (dict): If exists is True, contains keys 'formula', 'num_atoms',
            'num_frames', and 'format' describing the trajectory. Otherwise empty.
    """
    traj_path = pool.get_user_file_path("trajectory", file_hash)
    parsed = False
    summary = {}
    formats = [fmt for fmt in formats if fmt]

    if pool.remote:
        host = pool._get_remote_host(pool.get_pool_workers()[0])
        script = (
            "import json, sys; "
            "import ase.io; "
            f"path={traj_path!r}; formats={formats!r}; "
            "out={}; "
            "\nfor fmt in formats:\n"
            "    try:\n"
            "        atoms=ase.io.read(path, format=fmt, index=0)\n"
            "        frames=sum(1 for _ in ase.io.iread(path, format=fmt, index=':'))\n"
            "        out={'formula': atoms.get_chemical_formula(),\n"
            "             'num_atoms': len(atoms),\n"
            "             'num_frames': frames,\n"
            "             'format': fmt}\n"
            "        break\n"
            "    except Exception:\n"
            "        pass\n"
            "print(json.dumps(out))"
        )
        stdout, stderr, rc = host.execute(
            pool._build_remote_python_command(script)
        )
        if rc != 0:
            logger.warning(
                "Failed to summarize remote trajectory %s in pool %s: %s",
                traj_path,
                pool.name,
                stderr.strip(),
            )
        else:
            try:
                summary = json.loads(stdout.strip() or "{}")
                parsed = bool(summary)
            except json.JSONDecodeError:
                summary = {}
                parsed = False

        return parsed, summary

    for fmt in formats:
        try:
            atoms = ase.io.read(traj_path, format=fmt, index=0)
            summary = {
                "formula": atoms.get_chemical_formula(),
                "num_atoms": len(atoms),
                "num_frames": count_trajectory_frames(traj_path, fmt),
                "format": fmt,
            }
            parsed = True
            break
        except Exception:
            continue

    return parsed, summary
    

from .database import qdyndb

def extract_structure_metadata(
    input: InputT,
    resume: bool,
    prev_task_id: str,
    pool: WorkerPool,
) -> tuple[str | None, int | None]:
    """Extract (formula, num_atoms) from input or predecessor task."""
    formula = None
    num_atoms = None
    if resume and prev_task_id:
        prev_meta = qdyndb.get_task_metadata(prev_task_id)
        if prev_meta:
            formula = prev_meta.get("formula")
            num_atoms = prev_meta.get("num_atoms")
    elif input.stru:
        try:
            import io as _io
            from ase.io import read as ase_read
            atoms = ase_read(
                _io.StringIO(input.stru),
                format=input.stru_format or "vasp",
            )
            formula = atoms.get_chemical_formula()
            num_atoms = len(atoms)
        except Exception:
            logging.warning("Failed to parse structure metadata from POSCAR")
            
    elif input.stru_hash:
        
        parsed, summary = read_trajectory_summary(
            pool=pool,
            file_hash=input.stru_hash,
            formats=[input.stru_format],
        )

        if parsed:
            formula = summary.get("formula")
            num_atoms = summary.get("num_atoms")

    return formula, num_atoms
