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
from typing import Any, Literal, IO
import logging

from ase import Atoms
from ase.constraints import FixAtoms
from ase.io.formats import ioformats
import numpy as np
from scipy.linalg import eigh as eigh_

from .input import InputT
from .pool import WorkerPool
from .tools.pseuh import resolve_symbol, validate_pseudo_h_symbols, parse_pseudo_h_symbol
from .params import TRAJ_FNAME_MAPPING, TRAJ_FORMAT_MAPPING, VALENCE_ELECTRONS
from .params import XC_MAPPING, ALL_ORBITALS

logger = logging.getLogger(__name__)

def xc_mapping(software: str, xc: str, input: dict) -> dict:
    if software == 'vasp':
        if xc in ['PBE', 'Not above']:
            pass
        elif xc is 'HSE06':
            input['LHFCALC'] = True
            input['GGA'] = 'PE'
            input['HFSCREEN'] = 0.2
        else:
            input['GGA'] = XC_MAPPING[software][xc]
    elif software == 'openmx':
        if xc is 'Not above':
            pass
        else:
            input['scf.xctype'] = XC_MAPPING[software][xc]
    else:
        raise NotImplementedError(f"Unsupported software: {software}")
    return input


def select_orbitals(software: str, category: str | int) -> dict[str, str]:
    orbital_basis = {}
    for element, orbs in ALL_ORBITALS[software].items():
        for orb, cats in orbs.items():
            if category in cats:
                orbital_basis[element] = orb
    return orbital_basis


def stru_todict(stru: Atoms) -> dict[str, Any]:
    structure = stru.todict()
    if structure.get('constraints') is not None:
        structure['constraints'] = [i.todict() for i in structure['constraints']]  # type: ignore[index]
    return structure


def read_stru(stru_format: str, stru_file: str | Path | IO, pseudo_h: bool = False) -> Atoms:
    """Read a single structure from a file."""
    
    if isinstance(stru_file, (str, Path)):
        with open(stru_file, 'r') as f:
            content = f.read()
    else:
        content = stru_file.read()
    
    if pseudo_h:
        lines = content.splitlines(keepends=True)
        if stru_format == 'vasp':
            try:
                raw_symbols = lines[5].split()
                atom_counts = [int(x) for x in lines[6].split()]
            except Exception as e:
                raise ValueError("Failed to parse element symbols "
                                f"and counts from {stru_file}: {e}")
        else:
            raise ValueError(f"Unsupported stru_format: {stru_format!r}")
        
        validate_pseudo_h_symbols(raw_symbols)
        # Tag atoms by their pseudo-H charge (tag = charge × 100)
        tags: list[int] = []
        for sym, count in zip(raw_symbols, atom_counts):
            charge = parse_pseudo_h_symbol(sym)
            if charge is not None:
                tags.extend([round(charge * 100)] * count)
            else:
                tags.extend([0] * count)
        
        # Replace pseudo-H symbols with plain "H" so ASE can parse
        clean_symbols: list[str] = []
        for sym in raw_symbols:
            clean = ''.join(ch for ch in sym if ch.isalpha())
            if not clean:
                clean = sym
            clean_symbols.append(clean)
            
        if stru_format == 'vasp':
            lines[5] = ' '.join(clean_symbols) + '\n'
        else:
            raise ValueError(f"Unsupported stru_format: {stru_format!r}")
        
    if stru_format in ioformats:
        if pseudo_h:
            atoms = ase.io.read(io.StringIO(''.join(lines)), format=stru_format, index=0) # type: ignore
            atoms.set_tags(tags) # type: ignore
        else:
            atoms = ase.io.read(io.StringIO(content), format=stru_format, index=0) # type: ignore
            
        return atoms # type: ignore
    
    if stru_format == 'openmx-dat':
        # parse symbols, positions
        pattern = re.compile(r"<Atoms\.SpeciesAndCoordinates\s+(.*?)\s+Atoms\.SpeciesAndCoordinates>", re.I | re.S)
        try:
            match = pattern.search(content)
            lines = match.group(1).strip().splitlines() # type: ignore
            symbols, positions = [], []
            for line in lines:
                parts = line.split()
                symbols.append(parts[1])
                positions.append([float(x) for x in parts[2:5]])
        except Exception as e:
            raise ValueError(f"Failed to parse structure from {stru_file}: {e}")
        
        # cell
        pattern = re.compile(r"<Atoms\.UnitVectors\s+(.*?)\s+Atoms\.UnitVectors>", re.I | re.S)
        try:
            match = pattern.search(content)
            lines = match.group(1).strip().splitlines() # type: ignore
            cell = [[float(x) for x in line.split()] for line in lines]
        except Exception as e:
            raise ValueError(f"Failed to parse unit vectors from {stru_file}: {e}")
        
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
                raise ValueError(f"Failed to parse velocities from {stru_file}: {e}")
            
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
                raise ValueError(f"Failed to parse fixed atoms from {stru_file}: {e}")

        structure = Atoms(symbols, positions, cell=cell, pbc=True, velocities=velocities)
        if constraint_indices:
            structure.set_constraint(FixAtoms(indices=constraint_indices))
    else:
        raise NotImplementedError(f"Unsupported stru_format: {stru_format}")
    
    return structure


def read_strus(
    stru_format: str, 
    traj_path: str, 
    first_only: bool = False, 
    pseudo_h: bool = False,
    ) -> list[Atoms]:
    """Read structures from trajectory file.

    Args:
        stru_format: Trajectory formats supported in TRAJ_FORMAT_MAPPING
            (e.g. 'vasp-xdatcar', 'extxyz', 'lammps-data').
        traj_path: Explicit path to the trajectory file.

    Returns:
        List of ASE Atoms objects representing the structures.
    """
    f = open(traj_path)
    
    if pseudo_h:
        lines = f.readlines()
        if stru_format == 'vasp-xdatcar':
            try:
                raw_symbols = lines[5].split()
                atom_counts = [int(x) for x in lines[6].split()]
            except Exception as e:
                raise ValueError("Failed to parse element symbols "
                                f"and counts from {traj_path}: {e}")
        else:
            raise ValueError(f"Unsupported stru_format: {stru_format!r}")
        
        validate_pseudo_h_symbols(raw_symbols)
        # Tag atoms by their pseudo-H charge (tag = charge × 100)
        tags: list[int] = []
        for sym, count in zip(raw_symbols, atom_counts):
            charge = parse_pseudo_h_symbol(sym)
            if charge is not None:
                tags.extend([round(charge * 100)] * count)
            else:
                tags.extend([0] * count)
        
        # Replace pseudo-H symbols with plain "H" so ASE can parse
        clean_symbols: list[str] = []
        for sym in raw_symbols:
            clean = ''.join(ch for ch in sym if ch.isalpha())
            if not clean:
                clean = sym
            clean_symbols.append(clean)
            
        if stru_format == 'vasp-xdatcar':
            lines[5] = ' '.join(clean_symbols) + '\n'
        else:
            raise ValueError(f"Unsupported stru_format: {stru_format!r}")
    
    if stru_format in ioformats:
        index = 0 if first_only else ':'
        if pseudo_h:
            atoms = ase.io.read(io.StringIO(''.join(lines)), format=stru_format, index=index) # type: ignore
            if not isinstance(atoms, list):
                atoms.set_tags(tags) # type: ignore
                atoms = [atoms]
            else:
                for frame in atoms:
                    frame.set_tags(tags) # type: ignore
        else:
            content = f.read()
            atoms = ase.io.read(io.StringIO(content), format=stru_format, index=index)
            if not isinstance(atoms, list):
                atoms = [atoms]
              
    elif stru_format == 'openmx-md':
        atoms = []
        while True:
            line = f.readline()
            if not line:
                break
            natoms = int(line)
            line = f.readline() # time, energy, cell
            if "Cell_Vectors" in line:
                cell = np.asarray(line.split()[-9:], dtype=np.float64).reshape(3, 3)
                pbc = True
            else:
                cell = (0, 0, 0)
                pbc = False
            positions = []
            symbols = []
            for _ in range(natoms):
                line = f.readline()
                parts = line.split()
                symbols.append(parts[0])
                positions.append([float(x) for x in parts[1:4]])
            stru = Atoms(symbols, positions=positions, cell=cell, pbc=pbc)
            atoms.append(stru)
            if first_only:
                break
    else:
        raise NotImplementedError(f"Unsupported stru_format: {stru_format}")
    f.close()
    return atoms


def write_stru(
    stru_path: str | Path, 
    structure: Atoms, 
    stru_format: str,
    pseudo_h: bool = False,
    extras: str | None = None
) -> None:
    """Write ASE Atoms object to a structure file.

    Args:
        stru_path: Path to write the structure file to.
        structure: ASE Atoms object to write.
        stru_format: Structure format.
        pseudo_h: Whether to use pseudo-H.
        extras: Additional information to include in the structure file.
    """
    if pseudo_h:
        tags = structure.get_tags()
        symbols = structure.get_chemical_symbols()
        groups: list[tuple[str, int]] = []
        for sym, tag in zip(symbols, tags):
            eff = resolve_symbol(sym, tag)
            if groups and groups[-1][0] == eff:
                groups[-1] = (eff, groups[-1][1] + 1)
            else:
                groups.append((eff, 1))
    
    if stru_format in ioformats:
                
        with io.StringIO() as buffer:
            ase.io.write(buffer, structure, format=stru_format)
            lines = buffer.getvalue().splitlines(keepends=True)
            
        if pseudo_h:
            if stru_format == 'vasp':
                lines[5] = ' '.join(g[0] for g in groups) + '\n' # type: ignore
                lines[6] = ' '.join(str(g[1]) for g in groups) + '\n' # type: ignore
            else:
                raise NotImplementedError(f"Unsupported stru_format: {stru_format}")
            
        with open(stru_path, 'w') as f:
            f.writelines(lines)

    elif stru_format == 'openmx-dat':
        from .params import PSEUDO_POTENTIAL, ORBITAL_BASIS
    
        with open(stru_path, "w") as f:
            f.write(extras or "")
            
            natoms = len(structure)
            syms = []
            raw_syms = structure.get_chemical_symbols()
            syms_set = set()
            for s in raw_syms:
                if s not in syms_set:
                    syms.append(s)
                    syms_set.add(s)
            valence = [VALENCE_ELECTRONS['openmx'][s] for s in raw_syms]
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
                        s, ORBITAL_BASIS[s], PSEUDO_POTENTIAL['openmx'][s]
                    )
                )
            stru_lines.append("Definition.of.Atomic.Species>\n\n")

            # species and coordinates block
            stru_lines.append("<Atoms.SpeciesAndCoordinates\n")
            for i, (s, v) in enumerate(zip(raw_syms, valence)):
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
        raise NotImplementedError(f"Unsupported software: {stru_format}")

# write_strus not used in current codebase, so not supported to handle pseudo-H for now. 
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

# ------------------------------------------------------------------
# structure / trajectory metadata
# ------------------------------------------------------------------

def _parse_trajectory(traj_path: str, formats: list[str]):
    parsed = False
    summary = {}
    for fmt in formats:
            try:
                atoms = read_strus(fmt, traj_path, first_only=True)[0]
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


def count_trajectory_frames(path: str, stru_format: str) -> int:
    """Count frames in a trajectory file without loading all atoms into memory.

    Uses format-specific lightweight scanning when available, falls back
    to ASE iread for unknown formats.

    Args:
        path: Path to the trajectory file.
        stru_format: trajectory format string (e.g. 'vasp-xdatcar').
    """
    if stru_format == "vasp-xdatcar":
        # Scan for "Direct configuration=" markers — O(n) read, no Atoms created
        with open(path, "r", encoding="utf-8", errors="replace") as fd:
            count = sum(1 for line in fd if "Direct configuration=" in line)
        # If no markers found but file is readable (e.g. single-frame POSCAR),
        # fall back to ASE to determine actual frame count
        if count > 0:
            return count
    elif stru_format == "openmx-md":
        with open(path, "r", encoding="utf-8", errors="replace") as fd:
            count = sum(1 for line in fd if "time=" in line)
        if count > 0:
            return count
    
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
        import inspect
        host = pool._get_remote_host(pool.get_pool_workers()[0])
        script = (
            "import json, sys\n"
            "import ase\n"
            "import numpy as np\n"
            f"{inspect.getsource(read_strus)}\n"
            f"{inspect.getsource(count_trajectory_frames)}\n"
            f"{inspect.getsource(_parse_trajectory)}\n"
            f"parsed, summary = _parse_trajectory({traj_path!r}, {formats!r})\n"
            "print(json.dumps(summary))\n"
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

    else:
        parsed, summary = _parse_trajectory(traj_path, formats)

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
            with io.StringIO(input.stru) as s:
                atoms = read_stru(input.stru_format, s)
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
