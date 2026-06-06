"""Pseudo-hydrogen tool for surface passivation in VASP calculations.

Read slab structures with pseudo-hydrogen atoms (H\\d{3} placeholder symbols),
apply FixAtoms constraints, and write POSCAR + POTCAR for VASP.

Reference: 来自分享的对话.md, pseudoh.md
"""

import io
import re
import shutil
from pathlib import Path
from typing import IO

import ase.io
from ase import Atoms
from ase.constraints import FixAtoms

from ..params import PSEUDO_POTENTIAL

# Valid pseudo-hydrogen ZVAL charges
_VALID_PSEUDO_H_CHARGES: set[float] = {
    0.25, 0.33, 0.42, 0.5, 0.58, 0.66, 0.75, 1.00,
    1.25, 1.33, 1.5, 1.66, 1.75,
}


def read_stru_pseuh(stru_file: str | Path | IO, stru_format: str = 'vasp') -> Atoms:
    """Read a structure and apply pseudo-hydrogen passivation.

    Validates pseudo-hydrogen placeholder symbols (e.g. ``H050``) in the
    input, cleans them to plain ``H`` so ASE can parse, then restores
    pseudo-H identity via ASE tags and applies FixAtoms constraints.

    Parameters
    ----------
    stru_file:
        Path to the structure file, or the structure content as a string
        when *from_str* is True.
    stru_format:
        ASE I/O format string.  Currently only ``'vasp'`` is supported.
    """
    if isinstance(stru_file, (str, Path)):
        with open(stru_file, 'r') as f:
            lines = f.readlines()
    else:
        lines = stru_file.readlines()

    if stru_format == 'vasp':
        try:
            raw_symbols = lines[5].split()
            atom_counts = [int(x) for x in lines[6].split()]
        except Exception as e:
            raise ValueError("Failed to parse element symbols "
                             f"and counts from {stru_file}: {e}")
    else:
        raise ValueError(f"Unsupported stru_format: {stru_format!r}")

    # --- validate, clean, and tag ---
    _validate_pseudo_h_symbols(raw_symbols)

    # Replace pseudo-H symbols with plain "H" so ASE can parse
    clean_symbols: list[str] = []
    for sym in raw_symbols:
        clean = ''.join(ch for ch in sym if ch.isalpha())
        if not clean:
            clean = sym  # fallback — should not happen
        clean_symbols.append(clean)

    if stru_format == 'vasp':
        lines[5] = ' '.join(clean_symbols) + '\n'
    else:
        raise ValueError(f"Unsupported stru_format: {stru_format!r}")
    
    atoms = ase.io.read(io.StringIO(''.join(lines)), format=stru_format)

    # Tag atoms by their pseudo-H charge (tag = charge × 100)
    tags: list[int] = []
    for sym, count in zip(raw_symbols, atom_counts):
        charge = _parse_pseudo_h_symbol(sym)
        if charge is not None:
            tags.extend([round(charge * 100)] * count)
        else:
            tags.extend([0] * count)

    atoms.set_tags(tags) # type: ignore

    # Reorder: non-pseudo-H first, pseudo-H (tag > 0) last 
    order = sorted(range(len(atoms)), key=lambda i: 1 if tags[i] > 0 else 0)
    atoms = atoms[order] # type: ignore

    # Apply FixAtoms to pseudo-H atoms
    atoms = _fix_pseudo_h_atoms(atoms)

    return atoms

def write_stru_pseuh(
    software: str,
    folder: Path, 
    structure: Atoms, 
    pp_path: Path,
    extras: str | None = None
) -> None:
    
    tags = structure.get_tags()
    symbols = structure.get_chemical_symbols()
    effective: list[str] = []
    groups: list[tuple[str, int]] = []
    for sym, tag in zip(symbols, tags):
        eff = _resolve_symbol(sym, tag)
        effective.append(eff)
        if groups and groups[-1][0] == eff:
            groups[-1] = (eff, groups[-1][1] + 1)
        else:
            groups.append((eff, 1))
            
    unique_symbols: list[str] = []
    for s in effective:
        if s not in unique_symbols:
            unique_symbols.append(s)
            
    if software == 'vasp':
        # --- POSCAR ---
        poscar = folder / 'POSCAR'
        ase.io.write(poscar, structure, format='vasp', vasp5=True, sort=False)

        with open(poscar, 'r') as f:
            lines = f.readlines()
        lines[5] = ' '.join(g[0] for g in groups) + '\n'
        lines[6] = ' '.join(str(g[1]) for g in groups) + '\n'
        with open(poscar, 'w') as f:
            f.writelines(lines)

        # --- POTCAR ---
        with open(folder / 'POTCAR', 'w') as outf:
            for sym in unique_symbols:
                pp_file = pp_path / PSEUDO_POTENTIAL[software][sym] / 'POTCAR'
                if not pp_file.is_file():
                    raise FileNotFoundError(
                        f"POTCAR for symbol '{sym}' not found at: {pp_file}")
                with open(pp_file, 'r') as inf:
                    shutil.copyfileobj(inf, outf)
    else:
        raise ValueError(f"Unsupported software: {software!r}")
# ---------------------------------------------------------------------------
# Symbol <-> charge conversion
# ---------------------------------------------------------------------------

def _parse_pseudo_h_symbol(symbol: str) -> float | None: #TODO: may be deleted
    """Try to extract ZVAL charge from an arbitrary pseudo-H symbol.

    Handles multiple conventions:
    - Decimal:  "H.5" -> 0.5, "H.75" -> 0.75, "H1.25" -> 1.25
    - Our fmt:  "H050" -> 0.5, "H125" -> 1.25
    - Simple:   "H1" -> 1.0, "H2" -> 2.0

    Returns None if the symbol is not a recognised pseudo-H.
    """
    if not symbol.startswith('H') or symbol == 'H':
        return None
    rest = symbol[1:]
    if not rest:
        return None
    if '.' in rest:
        try:
            return float(rest)
        except ValueError:
            return None
    else:
        try:
            val = int(rest)
        except ValueError:
            return None
        # Heuristic: long digit strings or values > 10 → charge = val/100
        #             short digit strings with small values → direct charge
        if len(rest) >= 3 or val > 10:
            return val / 100.0
        else:
            return float(val)


# ---------------------------------------------------------------------------
# Pseudo-hydrogen structure reader
# ---------------------------------------------------------------------------

def _validate_pseudo_h_symbols(raw_symbols: list[str]) -> None:
    """Validate that all H-like symbols use H\\d{3} format with a valid charge.

    Raises ValueError if any pseudo-hydrogen symbol has an unrecognised
    format or invalid ZVAL charge.
    """
    h_like = [(sym, _parse_pseudo_h_symbol(sym))
              for sym in raw_symbols
              if sym.startswith('H') and sym != 'H']

    if not h_like:
        raise ValueError(
            "No pseudo-hydrogen symbols (H\\d{3}) found in structure. "
            "Expected placeholder symbols like H050, H075, etc."
        )
    bad = []
    for sym, charge in h_like:
        if charge is None or not re.fullmatch(r'H\d{3}', sym):
            bad.append(f"{sym} (must be H\\d{{3}} format)")
        elif charge not in _VALID_PSEUDO_H_CHARGES:
            bad.append(f"{sym} (charge {charge} is not a valid pseudo-H ZVAL)")
    if bad:
        raise ValueError(
            "Invalid pseudo-hydrogen symbols in structure: "
            + "; ".join(bad)
        )


# ---------------------------------------------------------------------------
# Write POSCAR + POTCAR
# ---------------------------------------------------------------------------

def _resolve_symbol(sym: str, tag: int) -> str:
    """Return the effective (placeholder) symbol for an atom.

    Pseudo-H atoms (tag > 0) get their placeholder symbol (e.g. "H050");
    plain-H or other elements keep their original symbol.
    """
    if sym == 'H' and tag > 0:
        return f"H{tag:03d}"''
    return sym


def _fix_pseudo_h_atoms(atoms: Atoms) -> Atoms:
    """Apply FixAtoms to all pseudo-H atoms (tag > 0), merging with existing ones.

    ASE will write ``Selective Dynamics`` and ``F F F`` for fixed atoms
    automatically when writing POSCAR with ``vasp5=True``.
    """
    tags = atoms.get_tags() # type: ignore
    pseudo_indices = [i for i, tag in enumerate(tags) if tag > 0]
    if not pseudo_indices:
        return atoms

    # Merge with any existing FixAtoms constraint
    fixed = set(pseudo_indices)
    for c in atoms.constraints:
        if isinstance(c, FixAtoms):
            fixed.update(c.index)

    atoms.set_constraint(FixAtoms(indices=sorted(fixed)))
    return atoms
