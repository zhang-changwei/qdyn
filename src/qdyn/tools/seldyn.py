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
