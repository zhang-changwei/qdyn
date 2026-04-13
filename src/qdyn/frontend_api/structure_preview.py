"""
Structure preview builder for 3D rendering.

Parses structure text via ASE and produces a format-agnostic
StructurePreviewPayload suitable for frontend 3D visualization.
"""

import io
import logging
from typing import List

import ase.io
from ase.constraints import FixAtoms

from .models import StructurePreviewPayload

logger = logging.getLogger(__name__)


def build_preview(content: str, fmt: str = "vasp") -> StructurePreviewPayload:
    """Parse structure text into a format-agnostic preview payload.

    Constraint extraction:
    - Scans atoms.constraints for FixAtoms -> index set -> bool mask
    - For FixCartesian/FixedLine/etc.: any axis constrained -> atom marked True
    - No constraints -> constraint_mask = None

    Non-periodic structures:
    - pbc from atoms.pbc
    - If all pbc=False, lattice may be zero matrix; renderer skips cell wireframe

    Args:
        content: Structure file content as a string.
        fmt: ASE I/O format string (default "vasp" for POSCAR).

    Returns:
        A StructurePreviewPayload with parsed structure data.

    Raises:
        ValueError: If ASE cannot parse the content.
    """
    try:
        atoms = ase.io.read(io.StringIO(content), format=fmt)
    except Exception as exc:
        raise ValueError(f"Failed to parse structure: {exc}") from exc

    if atoms is None:
        raise ValueError("Failed to parse structure: ASE returned None")

    species: List[str] = atoms.get_chemical_symbols()
    cart_coords: List[List[float]] = atoms.get_positions().tolist()
    lattice: List[List[float]] = atoms.cell.tolist()
    pbc: List[bool] = atoms.pbc.tolist()

    # Extract constraint mask from ASE constraints
    constraint_mask = _extract_constraint_mask(atoms)

    return StructurePreviewPayload(
        species=species,
        cart_coords=cart_coords,
        lattice=lattice,
        pbc=pbc,
        constraint_mask=constraint_mask,
    )


def _extract_constraint_mask(atoms) -> List[bool] | None:
    """Extract a per-atom boolean constraint mask from ASE constraints.

    Handles FixAtoms (fully constrained) and partial constraints
    (FixCartesian, FixedLine, FixedPlane, etc.) where any axis
    being constrained marks the atom as True.

    Returns None if there are no constraints at all.
    """
    if not atoms.constraints:
        return None

    n_atoms = len(atoms)
    mask = [False] * n_atoms
    has_any = False

    for constraint in atoms.constraints:
        if isinstance(constraint, FixAtoms):
            # FixAtoms stores constrained atom indices
            for idx in constraint.index:
                if 0 <= idx < n_atoms:
                    mask[idx] = True
                    has_any = True
        elif hasattr(constraint, "index"):
            # Partial constraints (FixCartesian, FixedLine, FixedPlane, etc.)
            # have an .index attribute (single int or array).
            # Any axis constrained -> atom marked True.
            indices = constraint.index
            if hasattr(indices, "__iter__"):
                for idx in indices:
                    if 0 <= idx < n_atoms:
                        mask[idx] = True
                        has_any = True
            else:
                idx = int(indices)
                if 0 <= idx < n_atoms:
                    mask[idx] = True
                    has_any = True

    return mask if has_any else None
