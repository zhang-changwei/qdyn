"""
Structure preview builder for 3D rendering.

Parses structure text via ASE and produces a format-agnostic
StructurePreviewPayload suitable for frontend 3D visualization.
"""

import io
import logging

from ..calc_common import read_stru
from ..tools.seldyn import extract_constraint_mask
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
        atoms = read_stru(fmt, io.StringIO(content))
    except Exception as exc:
        raise ValueError(f"Failed to parse structure: {exc}") from exc

    if atoms is None:
        raise ValueError("Failed to parse structure: ASE returned None")

    species: list[str] = atoms.get_chemical_symbols()
    cart_coords: list[list[float]] = atoms.get_positions().tolist()
    lattice: list[list[float]] = atoms.cell.tolist()
    pbc: list[bool] = atoms.pbc.tolist()

    # Extract constraint mask from ASE constraints
    constraint_mask = extract_constraint_mask(atoms)

    return StructurePreviewPayload(
        species=species,
        cart_coords=cart_coords,
        lattice=lattice,
        pbc=pbc,
        constraint_mask=constraint_mask,
    )
