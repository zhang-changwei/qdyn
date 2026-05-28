"""Pseudo-hydrogen tool for surface passivation in VASP calculations.

Read slab structures with pseudo-hydrogen atoms (H\\d{3} placeholder symbols),
apply FixAtoms constraints, and write POSCAR + POTCAR for VASP.

Reference: 来自分享的对话.md, pseudoh.md
"""

import io
import re
import shutil
from pathlib import Path
import ase.io
from ase import Atoms
from ase.constraints import FixAtoms

from ..params import potcar_default

# Valid pseudo-hydrogen ZVAL charges
_VALID_PSEUDO_H_CHARGES: set[float] = {
    0.25, 0.33, 0.42, 0.5, 0.58, 0.66, 0.75, 1.00,
    1.25, 1.33, 1.5, 1.66, 1.75,
}


# ---------------------------------------------------------------------------
# Symbol <-> charge conversion
# ---------------------------------------------------------------------------

def _charge_to_symbol(charge: float) -> str:
    """Convert ZVAL charge to placeholder symbol.

    0.50 -> "H050", 1.25 -> "H125"
    """
    charge = round(charge, 2)
    return f"H{round(charge * 100):03d}"


def _symbol_to_charge(symbol: str) -> float:
    """Reverse of _charge_to_symbol.

    "H050" -> 0.50, "H125" -> 1.25
    """
    digits = symbol[1:]  # strip leading 'H'
    return int(digits) / 100.0


def _charge_to_potcar_dir(charge: float) -> str:
    """Convert ZVAL charge to VASP POTCAR directory name.

    0.50 -> "H.5", 0.75 -> "H.75", 1.0 -> "H", 1.25 -> "H1.25"
    """
    charge = round(charge, 2)
    if charge == 1.0:
        return "H"
    s = str(charge)
    if charge < 1.0:
        return f"H.{s.split('.')[1]}"
    else:
        return f"H{s}"


def _is_pseudo_h_symbol(symbol: str) -> bool:
    """Check if a symbol is a pseudo-hydrogen placeholder, e.g. "H050", "H125"."""
    return bool(re.fullmatch(r'H\d{3}', symbol))


def _parse_pseudo_h_symbol(symbol: str) -> float | None:
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


def read_stru_pseuh(
    source: str, stru_format: str = 'vasp', *, from_str: bool = False,
) -> Atoms:
    """Read a structure and apply pseudo-hydrogen passivation.

    Validates pseudo-hydrogen placeholder symbols (e.g. ``H050``) in the
    input, cleans them to plain ``H`` so ASE can parse, then restores
    pseudo-H identity via ASE tags and applies FixAtoms constraints.

    Parameters
    ----------
    source:
        Path to the structure file, or the structure content as a string
        when *from_str* is True.
    stru_format:
        ASE I/O format string.  Currently only ``'vasp'`` is supported.
    from_str:
        If True, *source* is interpreted as structure text instead of
        a file path.
    """
    if from_str:
        lines = source.splitlines(keepends=True)
    else:
        with open(source, 'r') as fh:
            lines = fh.readlines()

    if len(lines) < 7:
        raise ValueError("Structure does not look like a valid POSCAR (need ≥7 lines)")

    if stru_format == 'vasp':
        raw_symbols = lines[5].split()
        atom_counts = [int(x) for x in lines[6].split()]
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
    atoms = atoms[order]

    # Apply FixAtoms to pseudo-H atoms
    atoms = _fix_pseudo_h_atoms(atoms)

    return atoms


# ---------------------------------------------------------------------------
# Write POSCAR + POTCAR
# ---------------------------------------------------------------------------

def _resolve_symbol(sym: str, tag: int) -> str:
    """Return the effective (placeholder) symbol for an atom.

    Pseudo-H atoms (tag > 0) get their placeholder symbol (e.g. "H050");
    plain-H or other elements keep their original symbol.
    """
    if sym == 'H' and tag > 0:
        return _charge_to_symbol(tag / 100.0)
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


def _write_poscar_manually(atoms: Atoms, filepath: Path) -> None:
    """Write POSCAR via ASE, then patch element lines for pseudo-H symbols.

    ASE handles constraints (Selective Dynamics), cell vectors, and
    coordinate formatting.  We post-patch the 6th and 7th lines to
    replace plain ``H`` with pseudo-H placeholder symbols (e.g. ``H050``).

    ``sort=False`` ensures ASE preserves the atom ordering, so the
    effective-symbol groups we build below match the coordinate section.
    """
    ase.io.write(filepath, atoms, format='vasp', vasp5=True, sort=False)

    with open(filepath, 'r') as f:
        lines = f.readlines()

    tags = atoms.get_tags()
    symbols = atoms.get_chemical_symbols()

    groups: list[tuple[str, int]] = []
    for sym, tag in zip(symbols, tags):
        eff = _resolve_symbol(sym, tag)
        if groups and groups[-1][0] == eff:
            groups[-1] = (eff, groups[-1][1] + 1)
        else:
            groups.append((eff, 1))

    lines[5] = ' '.join(g[0] for g in groups) + '\n'
    lines[6] = ' '.join(str(g[1]) for g in groups) + '\n'

    with open(filepath, 'w') as f:
        f.writelines(lines)


def write_poscar_and_potcar(
    atoms: Atoms,
    pp_path: str | Path,
    output_dir: str | Path,
    pseudo_map: dict[str, str] | None = None,
    potcar_map: dict[str, str] | None = None,
) -> None:
    """Write POSCAR and POTCAR files ready for VASP.

    Parameters
    ----------
    atoms:
        Structure including pseudo-H placeholder symbols.
    pp_path:
        Root of the VASP pseudopotential library tree.
    output_dir:
        Directory to write ``POSCAR`` and ``POTCAR`` into.
    pseudo_map:
        Override the placeholder-symbol -> POTCAR-directory mapping,
        e.g. ``{"H050": "H.5_GW"}``.
    potcar_map:
        Add / override entries in the real-element POTCAR map
        (``potcar_default`` from :mod:`qdyn.params`).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pp_path = Path(pp_path).expanduser().resolve()

    # --- POSCAR (manual writer for placeholder symbols) ---
    _write_poscar_manually(atoms, output_dir / 'POSCAR')

    # --- POTCAR ---
    tags = atoms.get_tags()
    symbols = atoms.get_chemical_symbols()
    effective: list[str] = []
    for sym, tag in zip(symbols, tags):
        effective.append(_resolve_symbol(sym, tag))

    unique_symbols: list[str] = []
    for s in effective:
        if s not in unique_symbols:
            unique_symbols.append(s)

    with open(output_dir / 'POTCAR', 'wb') as outf:
        for sym in unique_symbols:
            if _is_pseudo_h_symbol(sym):
                charge = _symbol_to_charge(sym)
                pp_dir = (pseudo_map or {}).get(sym, _charge_to_potcar_dir(charge))
            else:
                pp_dir = (potcar_map or {}).get(sym) or potcar_default.get(sym, sym)

            pp_file = pp_path / pp_dir / 'POTCAR'
            if not pp_file.is_file():
                raise FileNotFoundError(
                    f"POTCAR for symbol '{sym}' not found at: {pp_file}"
                )
            with open(pp_file, 'rb') as inf:
                shutil.copyfileobj(inf, outf)


