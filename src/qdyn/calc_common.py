import ast
from contextlib import contextmanager
import io
import json
import operator
import os
import re
from pathlib import Path
from ase import Atoms
import ase.io
from typing import Any, Literal
import logging

from ase import Atoms
from ase.constraints import FixAtoms
import numpy as np
from scipy.linalg import eigh as eigh_

from .input import InputT
from .pool import WorkerPool
from .tools.pseuh import read_stru_pseuh
from .params import TRAJ_FNAME_MAPPING, TRAJ_FORMAT_MAPPING, VALENCE_ELECTRONS

logger = logging.getLogger(__name__)

def read_stru(stru_format: str, stru_path: str) -> Atoms:
    """Read a single structure from a file."""
    if stru_format == 'vasp':
        return ase.io.read(stru_path, format='vasp')
    elif stru_format == 'openmx-dat':
        with open(stru_path) as f:
            content = f.read()
            # parse symbols, positions
            pattern = re.compile(r"<Atoms\.SpeciesAndCoordinates\s+(.*?)\s+Atoms\.SpeciesAndCoordinates>", re.I | re.S)
            try:
                match = pattern.search(content)
                lines = match.group(1).strip().splitlines()
                symbols, positions = [], []
                for line in lines:
                    parts = line.split()
                    symbols.append(parts[1])
                    positions.append([float(x) for x in parts[2:5]])
            except Exception as e:
                raise ValueError(f"Failed to parse structure from {stru_path}: {e}")
            
            # cell
            pattern = re.compile(r"<Atoms\.UnitVectors\s+(.*?)\s+Atoms\.UnitVectors>", re.I | re.S)
            try:
                match = pattern.search(content)
                lines = match.group(1).strip().splitlines()
                cell = [[float(x) for x in line.split()] for line in lines]
            except Exception as e:
                raise ValueError(f"Failed to parse unit vectors from {stru_path}: {e}")
            
            # velocities
            velocities = None
            pattern = re.compile(r"<MD\.Init\.Velocity\s+(.*?)\s+MD\.Init\.Velocity>", re.I | re.S)
            match = pattern.search(content)
            if match:
                try:
                    lines = match.group(1).strip().splitlines()
                    velocities = []
                    for line in lines:
                        parts = line.split()
                        velocities.append([float(x) for x in parts[1:4]])
                    velocities = np.array(velocities) * 1e-5
                except Exception as e:
                    raise ValueError(f"Failed to parse velocities from {stru_path}: {e}")
                
            # constraints (MD.Fixed.XYZ)
            constraint_indices = []
            pattern = re.compile(r"<MD\.Fixed\.XYZ\s+(.*?)\s+MD\.Fixed\.XYZ>", re.I | re.S)
            match = pattern.search(content)
            if match:
                try:
                    lines = match.group(1).strip().splitlines()
                    for line in lines:
                        parts = line.split()
                        idx = int(parts[0]) - 1
                        flags = [int(x) for x in parts[1:4]]
                        if all(f == 1 for f in flags):
                            constraint_indices.append(idx)
                except Exception as e:
                    raise ValueError(f"Failed to parse fixed atoms from {stru_path}: {e}")

            structure = Atoms(symbols, positions, cell=cell, pbc=True, velocities=velocities)
            if constraint_indices:
                structure.set_constraint(FixAtoms(indices=constraint_indices))
    else:
        raise NotImplementedError(f"Unsupported stru_format: {stru_format}")
    
    return structure


def read_strus(stru_format: str, traj_path: str) -> list[Atoms]:
    """Read structures from trajectory file.

    Args:
        stru_format: Trajectory format alias or ASE format string
            (e.g. 'vasp-xdatcar', 'extxyz', 'lammps-data').
        traj_path: Explicit path to the trajectory file.

    Returns:
        List of ASE Atoms objects representing the structures.
    """
    return ase.io.read(traj_path, format=stru_format, index=':')


def write_stru(
    software: str, 
    structure: Atoms, 
    out_dir: str | Path, 
    extras: str | None = None
) -> None:
    """Write ASE Atoms object to a structure file.

    Args:
        software: Software name ('vasp', 'cp2k', etc.).
        structure: ASE Atoms object to write.
        out_dir: Path to output structure file.
        extras: Additional information to include in the structure file.
    """
    if software == 'vasp':
        ase.io.write(
            os.path.join(out_dir, "POSCAR"), structure, vasp5=True, direct=True
        )
    elif software == 'openmx':
        from .params import PSEUDO_POTENTIAL, ORBITAL_BASIS

        with open(os.path.join(out_dir, "qdyn.dat"), "w") as f:
            f.write(extras or "")
            
            natoms = len(structure)
            syms = []
            raw_syms = structure.get_chemical_symbols()
            syms_set = set()
            for s in raw_syms:
                if s not in syms_set:
                    syms.append(s)
                    syms_set.add(s)
            valence = [VALENCE_ELECTRONS['openmx'][s] for s in syms]
            pos = structure.get_positions()
            cell = structure.get_cell().array

            stru_lines = []
            stru_lines.append(
                f"\n\n"
                f"Species.Number             {len(syms)}\n"
                f"Atoms.Number                  {natoms}\n"
                f"Atoms.SpeciesAndCoordinates.Unit   Ang\n"
                f"Atoms.UnitVectors.Unit             Ang\n\n"
            )
            # PAO and VPS block
            stru_lines.append("<Definition.of.Atomic.Species\n")
            for s in syms:
                stru_lines.append(
                    " {:3s} {:18s} {:10s}\n".format(
                        s, ORBITAL_BASIS['openmx'][s], PSEUDO_POTENTIAL['openmx'][s]
                    )
                )
            stru_lines.append("Definition.of.Atomic.Species>\n\n")

            # species and coordinates block
            stru_lines.append("<Atoms.SpeciesAndCoordinates\n")
            for i, (s, v) in enumerate(zip(syms, valence)):
                stru_lines.append(
                    " {:5d} {:3s} {:12.8f} {:12.8f} {:12.8f} {:4.1f} {:4.1f}\n".format(
                        i+1, s, pos[i,0], pos[i,1], pos[i,2], v/2, v/2
                    )
                )
            stru_lines.append("Atoms.SpeciesAndCoordinates>\n\n")

            # unit vectors block
            stru_lines.append("<Atoms.UnitVectors\n")
            for i in range(3):
                stru_lines.append(
                    " {:12.8f} {:12.8f} {:12.8f}\n".format(
                        cell[i,0], cell[i,1], cell[i,2]
                    )
                )
            stru_lines.append("Atoms.UnitVectors>\n\n")

            # velocities block (unit: m/s)
            if 'momenta' in structure.arrays: 
                vels = structure.get_velocities() * 1e5
                stru_lines.append("<MD.Init.Velocity\n")
                for i in range(natoms):
                    stru_lines.append(
                        " {:5d} {:12.6f} {:12.6f} {:12.6f}\n".format(
                            i+1, vels[i,0], vels[i,1], vels[i,2]
                        )
                    )
                stru_lines.append("MD.Init.Velocity>\n\n")
            
            # constraints block (MD.Fixed.XYZ)
            fixed_mask = [False] * natoms
            if structure.constraints:
                for constraint in structure.constraints:
                    if isinstance(constraint, FixAtoms):
                        for idx in constraint.index:
                            if 0 <= idx < natoms:
                                fixed_mask[idx] = True
            stru_lines.append("<MD.Fixed.XYZ\n")
            for i in range(natoms):
                flags = "1 1 1" if fixed_mask[i] else "0 0 0"
                stru_lines.append(f" {i + 1:5d}  {flags}\n")
            stru_lines.append("MD.Fixed.XYZ>\n\n")

            f.write("".join(stru_lines))
            f.flush()
    else:
        raise NotImplementedError(f"Unsupported software: {software}")


def write_strus(software: str, structures: list[Atoms], out_dir: str | Path = '.') -> str:
    """Write structures to a trajectory file in software-native format.

    Args:
        software: Software name ('vasp', 'cp2k', etc.).
        structures: List of ASE Atoms objects to write.
        out_dir: Directory to write the trajectory file into. Default is
            current directory.

    Returns:
        Path to the written trajectory file.
    """
    traj_name = TRAJ_FNAME_MAPPING.get(software)
    if traj_name is None:
        raise ValueError(f"Unsupported software: {software}")
    ase_format = TRAJ_FORMAT_MAPPING.get(software)
    if ase_format is None:
        raise ValueError(f"Unsupported software: {software}")
    track_file = os.path.join(out_dir, traj_name)
    ase.io.write(track_file, structures, format=ase_format)
    return track_file

# def read_stru(
#     stru: str,
#     stru_format: str = 'vasp',
#     pseudo_h: bool = False,
#     from_str: bool = False,
# ) -> Atoms:
#     """Read a single structure from a file path or string.

#     Args:
#         stru: Path to the structure file, or the structure content as a
#             string when *from_str* is True.
#         stru_format: ASE I/O format string (e.g. ``'vasp'`` for POSCAR).
#         pseudo_h: If True, treat pseudo-hydrogen placeholder symbols
#             (e.g. ``H050``) and apply FixAtoms.  Delegates to
#             :func:`qdyn.tools.pseuh.read_stru_pseuh`.
#         from_str: If True, *stru* is interpreted as structure text
#             instead of a file path.

#     Returns:
#         ASE Atoms object.
#     """
#     if pseudo_h:
#         return read_stru_pseuh(stru, stru_format=stru_format, from_str=from_str)

#     if from_str:
#         return ase.io.read(io.StringIO(stru), format=stru_format) # type: ignore
#     else:
#         return ase.io.read(stru, format=stru_format) # type: ignore


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


@contextmanager
def change_dir(path: str | Path):
    """Context manager to temporarily change the working directory."""
    prev_dir = Path.cwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(prev_dir)


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

def eigh(H, S, solver: Literal['scipy', 'cuda'] = 'scipy', overwrite_S=False):
    if solver == 'scipy':
        w, v = eigh_(H, S, overwrite_a=True, overwrite_b=overwrite_S)
        v = v.T       
    else:
        raise NotImplementedError("Not supported eigensolver")
    return w, v
