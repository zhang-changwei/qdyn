import logging
from typing import Tuple

import numpy as np
from ase import Atoms, geometry
from ase.constraints import FixAtoms

from ..input import SelDynInputT


def add_constraints(
    structure: Atoms,
    sel: SelDynInputT,
) -> Atoms:
    """Add layer-based constraints to the structure.

    Parameters
    ----------
    structure : Atoms
        ASE Atoms object representing the structure.
    sel : SelDynInputT

    """

    # Get layer indices based on geometry
    miller = np.array(list(sel.layer_direction), dtype=int)  # type: ignore

    _, layers = auto_tolerance(structure, miller, sel.total_layers)  # type: ignore

    clayers = np.array(sel.constraint_layers, dtype=int) - 1

    mask = np.isin(layers[0], clayers)
    c = FixAtoms(mask=mask)
    structure.set_constraint(c)
    return structure


def auto_tolerance(
    structure: Atoms,
    miller: np.ndarray,
    target: int,
    low: float = 0.01,
    high: float = 10,
    max_iter: int = 30,
) -> Tuple[float, tuple]:

    for _ in range(max_iter):
        mid = (low + high) / 2
        layers = geometry.get_layers(structure, miller, tolerance=mid)
        n = len(layers[1])
        if n == target:
            return mid, layers
        elif n > target:
            low = mid
        else:
            high = mid

    logging.warning(
        f"Can't split the structure into {target} layers within {max_iter} iterations. "
        f"Final layer distances: {mid:.4f}, layers found: {n}."
    )
    return low, geometry.get_layers(structure, miller, tolerance=low)


def extract_constraint_mask(atoms: Atoms) -> list[bool] | None:
    """Extract a per-atom boolean constraint mask from ASE constraints.

    Reads existing constraints (FixAtoms, FixCartesian, FixedLine,
    FixedPlane, etc.) already set on the Atoms object.

    Handles FixAtoms (fully constrained) and partial constraints
    where any axis being constrained marks the atom as True.

    Returns None if there are no constraints at all.

    Parameters
    ----------
    atoms : Atoms
        ASE Atoms object, possibly with constraints set (e.g. from
        selective dynamics in a POSCAR file).

    Returns
    -------
    list[bool] | None
        Per-atom constraint mask, or None if no constraints exist.
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
