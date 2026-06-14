"""
Structure preview builder for 3D rendering.

Parses structure text via ASE and produces a format-agnostic
StructurePreviewPayload suitable for frontend 3D visualization.
"""

import io
import logging

import ase.io
import numpy as np
from ase import Atoms

from ..calc_common import has_valid_cell, read_stru
from ..tools.seldyn import extract_constraint_mask
from .models import StructurePreviewPayload

logger = logging.getLogger(__name__)

def atoms_to_vasp_text(atoms: Atoms) -> str:
    """Serialize ASE atoms to POSCAR/VASP text without reordering atoms."""
    buf = io.StringIO()
    ase.io.write(
        buf,
        atoms,
        format="vasp",
        direct=True,
        vasp5=True,
        sort=False,
    )
    return buf.getvalue()


def build_preview_from_atoms(atoms: Atoms) -> StructurePreviewPayload:
    """Build the additive preview payload from an ASE Atoms object."""
    preview_atoms = atoms

    species: list[str] = preview_atoms.get_chemical_symbols()
    cart_coords: list[list[float]] = preview_atoms.get_positions().tolist()
    lattice: list[list[float]] = preview_atoms.cell.tolist()
    pbc: list[bool] = atoms.pbc.tolist()
    constraint_mask = extract_constraint_mask(preview_atoms)

    return StructurePreviewPayload(
        species=species,
        cart_coords=cart_coords,
        lattice=lattice,
        pbc=pbc,
        constraint_mask=constraint_mask,
        format="vasp",
        content=atoms_to_vasp_text(preview_atoms),
    )


def build_preview(content: str, fmt: str = "vasp") -> StructurePreviewPayload:
    """Parse structure text into a format-agnostic preview payload.

    Constraint extraction:
    - Scans atoms.constraints for FixAtoms -> index set -> bool mask
    - For FixCartesian/FixedLine/etc.: any axis constrained -> atom marked True
    - No constraints -> constraint_mask = None

    Non-periodic structures:
    - pbc is preserved from the source atoms.
    - If the source has no valid cell, a display-only bounding cell is used
      for legacy coordinates/lattice and VASP preview content.

    Args:
        content: Structure file content as a string.
        fmt: ASE I/O format string (default "vasp" for POSCAR).

    Returns:
        A StructurePreviewPayload with parsed structure data.

    Raises:
        ValueError: If ASE cannot parse the content.
    """
    try:
        atoms = read_stru(fmt, io.StringIO(content))
    except Exception as exc:
        raise ValueError(f"Failed to parse structure: {exc}") from exc

    if atoms is None:
        raise ValueError("Failed to parse structure: ASE returned None")

    return build_preview_from_atoms(atoms)
