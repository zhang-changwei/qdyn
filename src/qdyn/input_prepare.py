import io
import math
import os
import glob
from pathlib import Path
import shutil
from typing import Any, Dict, List, Tuple, Union

import ase.io
import numpy as np
from ase import Atoms
from pymatgen.io.vasp import Incar

from .params import potcar_default


class DFTInputs:

    def __init__(
        self,
        software: str,
        structure: Atoms | None = None,
        pp_path: str | Path | None = None,
        orb_path: str | Path | None = None,
        kspacing: float | None = None,
        inputs_dict: dict | None = None,
        inputs_params: str = '',
    ):
        # init 
        self.allow_modify = True
        self._stru: Atoms | None = structure
        self._pp_path = Path(pp_path) if pp_path is not None else None
        self._orb_path = Path(orb_path) if orb_path is not None else None
        self._kpoints: tuple[int, int, int] | None = None
        self._gamma: bool | None = None
        self._inputs: dict[str, Any] | None = None
        self._nbands: int | None = None

        self.software = software

        # Step 0: STRU
        # Step 1: KPOINTS
        if kspacing is not None:
            self._kpoints = self.calc_kpoints(kspacing)
        # Step 2: INPUTS
        if inputs_dict is not None:
            self._inputs = self.update_inputs(inputs_dict, inputs_params)


    @classmethod
    def from_file(
        cls, 
        software: str, 
        stru_file: str | Path | None = None,
        kpoints_file: str | Path | None = None,
        inputs_file: str | Path | None = None,
    ):
        # init 
        cls.allow_modify = False
        cls._stru: Atoms | None = None
        cls._pp_path = None
        cls._orb_path = None
        cls._kpoints: tuple[int, int, int] | None = None
        cls._gamma: bool | None = None
        cls._inputs: dict[str, Any] | None = None
        cls._nbands: int | None = None

        cls.software = software

        if software == 'vasp':
            if stru_file is not None:
                cls._stru = ase.io.read(stru_file, format='vasp')
            if kpoints_file is not None:
                from pymatgen.io.vasp import Kpoints

                kpoints = Kpoints.from_file(kpoints_file)
                cls._kpoints = tuple(kpoints.kpts[0])
            if inputs_file is not None:
                incar = Incar.from_file(inputs_file)
                cls._inputs = incar.as_dict()
        else:
            raise NotImplementedError(f"Software '{software}' is not supported yet.")


    @property
    def stru(self) -> Atoms:
        if not self._stru:
            raise ValueError("Structure is not set.")
        return self._stru
    
    @property
    def pp_path(self) -> Path:
        if not self._pp_path:
            raise ValueError("Pseudopotential path is not set.")
        return self._pp_path
    
    @property
    def orb_path(self) -> Path:
        if not self._orb_path:
            raise ValueError("Orbital path is not set.")
        return self._orb_path
    
    @property
    def kpoints(self) -> tuple[int, int, int]:
        if self._kpoints is None:
            raise ValueError("K-points are not set.")
        return self._kpoints

    @property
    def gamma(self) -> bool:
        if self._gamma is None:
            self._gamma = True if self.kpoints == (1, 1, 1) else False
        return self._gamma
    
    @property
    def inputs(self) -> dict[str, Any]:
        if self._inputs is None:
            raise ValueError("Inputs are not set.")
        return self._inputs
    
    def calc_kpoints(self, kspacing: float) -> tuple[int, int, int]:
        rec_cell = self.stru.cell.reciprocal().array

        kpoints = []
        for i in range(3):
            length = np.linalg.norm(rec_cell[i])
            nk = max(1, length / kspacing)
            kpoints.append(nk)
        kpoints = symmetric_kpoints(self.stru, kpoints)

        return tuple(kpoints) # type: ignore
    
    def update_inputs(self, inputs_dict: dict, inputs_params: str) -> dict:
        if self.software == 'vasp':
            incar = Incar.from_dict(inputs_dict)
            if inputs_params:
                incar_append = Incar.from_str(inputs_params)
                incar.update(incar_append)

            if self.gamma:
                incar['KPAR'] = 1
            else:
                kx, ky, kz = self.kpoints
                nk = (kx//2) * (ky//2) * (kz//2) # Gamma-centered
                incar['KPAR'] = (8 if nk >= 8 
                                   else 4 if nk >= 4 
                                   else 2 if nk >= 2 
                                   else 1)
            return incar.as_dict()
        else:
            raise NotImplementedError(f"Software '{self.software}' is not supported yet.")

    def write(
        self,
        software: str | None = None,
        folder: str | Path = ".", 
        input: bool = True,
        kpoints: bool = True,
        stru: bool = True,
        pp: bool = True,
    ) -> None:
        folder = Path(folder)
        if not software:
            software = self.software

        if input:
            self.write_inputs(software, folder)
        if kpoints:
            self.write_kpoints(software, folder)
        if stru:
            STRU_FNAME = {"vasp": "POSCAR"}
            STRU_FORMAT = {"vasp": "vasp"}
            ase.io.write(folder / STRU_FNAME[software], 
                         self.stru, 
                         format=STRU_FORMAT[software])
        if pp:
            self.write_pp(software, folder)

    def write_inputs(self, software: str, folder: Path):
        if software == 'vasp':
            incar = Incar.from_dict(self.inputs)
            incar.write_file(folder / 'INCAR')
        else:
            raise NotImplementedError(f"Software '{software}' is not supported yet.")

    def write_kpoints(self, software: str, folder: Path):
        kpoints = self.kpoints

        if software == 'vasp':
            with open(folder / 'KPOINTS', 'w') as f:
                f.write("KPOINTS generated by QDYN\n")
                f.write("0\n")
                f.write("Gamma\n")
                f.write(f"{kpoints[0]} {kpoints[1]} {kpoints[2]}\n")
                f.write("0.0 0.0 0.0\n")
        else:
            raise NotImplementedError(f"Software '{software}' is not supported yet.")

    def write_pp(self, software: str, folder: Path):        
        if software == 'vasp':
            symbols = self.stru.get_chemical_symbols()
            unique_symbols: list[str] = []
            for s in symbols:
                if s not in unique_symbols:
                    unique_symbols.append(s)

            with open(folder / 'POTCAR', 'w') as outf:
                for s in unique_symbols:
                    pp_file = self.pp_path / potcar_default.get(s, s) / "POTCAR"
                    if not pp_file.is_file():
                        raise FileNotFoundError(
                            f"POTCAR for element {s} not found in {self.pp_path}.")
                    with open(pp_file, 'r') as inf:
                        shutil.copyfileobj(inf, outf)
        else:
            raise NotImplementedError(f"Software '{software}' is not supported yet.")


# ===========================================================================
# VASP specific functions
# ===========================================================================


def prepare_vasp_inputs(
    structure: Atoms,
    pp_path: str,
    kspacing: float,
    incar_dict: dict,
    incar_params: str = '',
):
    """Prepare VASP input files (POSCAR, KPOINTS, POTCAR, INCAR) in current directory.

    Parameters
    ----------
    structure : Atoms
        Atomic structure.
    pp_path : str
        Path to VASP pseudopotential directory.
    kspacing : float
        K-point spacing in 1/Å. Used to generate KPOINTS.
    incar_dict : dict
        Base INCAR parameters dictionary.
    incar_params : str, optional
        Additional INCAR parameters in KEY=VALUE format string (will override defaults).
    """
    # Write POSCAR
    ase.io.write('POSCAR', structure, format='vasp')

    # Write KPOINTS
    prepare_kpoints(structure, kspacing)

    # Write POTCAR
    prepare_potcar(structure, pp_path)

    # Write INCAR
    prepare_incar(incar_dict=incar_dict, incar_params=incar_params)


def prepare_kpoints(structure: Atoms, kspacing: float):
    """Generate KPOINTS file based on k-point spacing.

    Parameters
    ----------
    structure : Atoms
        Atomic structure (used to get cell parameters).
    kspacing : float
        K-point spacing in 1/Å.
    """
    rec_cell = structure.cell.reciprocal().array

    kpoints = []
    for i in range(3):
        length = np.linalg.norm(rec_cell[i])
        nk = max(1, length / kspacing)
        kpoints.append(nk)
    kpoints = symmetric_kpoints(structure, kpoints)

    return kpoints


def symmetric_kpoints(structure: Atoms, kpoints: list[float]) -> List[int]:
    kpoints_rev = [int(k + 0.5) for k in kpoints]
    mask = has_vacuum(structure)
    for i in range(3):
        if mask[i]:
            kpoints_rev[i] = 1
    return kpoints_rev


def has_vacuum(stru: Atoms, threshold: float = 10.0) -> Tuple[bool, bool, bool]:
    frac = stru.get_scaled_positions()
    frac_min = np.min(frac, axis=0)
    frac_max = np.max(frac, axis=0)
    cell_length = stru.cell.lengths()
    thickness = cell_length * (1 - (frac_max - frac_min))
    return thickness > threshold


def prepare_potcar(structure: Atoms, pp_path: str):
    """Generate POTCAR file by concatenating pseudopotentials.

    Parameters
    ----------
    structure : Atoms
        Atomic structure (used to get element types).
    pp_path : str
        Path to VASP pseudopotential directory.
    """
    # Get unique elements in order of appearance
    pp_path = os.path.expanduser(pp_path)
    symbols = structure.get_chemical_symbols()
    unique_symbols = []
    for s in symbols:
        if s not in unique_symbols:
            unique_symbols.append(s)

    with open('POTCAR', 'w') as outf:
        for symbol in unique_symbols:
            # Try common POTCAR naming conventions
            try:
                potcars = glob.glob(os.path.join(pp_path, "*POTCAR*"))

                potcar_file = None
                for candidate in potcars:
                    if symbol in candidate:
                        potcar_file = candidate
                        break
                if potcar_file is None:
                    raise FileNotFoundError
            except Exception:
                potcar_file = os.path.join(pp_path, potcar_default[symbol], 'POTCAR')

            if not os.path.isfile(potcar_file):
                raise FileNotFoundError(
                    f"POTCAR for element {symbol} not found in {pp_path}. "
                )

            with open(potcar_file, 'r') as inf:
                shutil.copyfileobj(inf, outf)


def prepare_incar(
    incar_dict: dict,
    incar_params: str = '',
):
    """Generate INCAR file for VASP calculation.

    Parameters are applied in the following order (later overrides earlier):
    1. incar_dict (base parameters)
    2. incar_params (additional parameters in KEY=VALUE format string)

    Parameters
    ----------
    incar_dict : dict
        Base INCAR parameters dictionary.
    incar_params : str, optional
        Additional INCAR parameters in KEY=VALUE format string.
    """
    incar = Incar.from_dict(incar_dict)
    if incar_params:
        incar_append = Incar.from_str(incar_params)
        incar.update(incar_append)

    incar.write_file('INCAR')
