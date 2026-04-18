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
        self._pp_path = (Path(pp_path).expanduser().resolve() 
                         if pp_path is not None else None)
        self._orb_path = (Path(orb_path).expanduser().resolve() 
                          if orb_path is not None else None)
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
    ) -> "DFTInputs":
        obj = cls(software=software)
        obj.allow_modify = False

        if software == 'vasp':
            if stru_file is not None:
                obj._stru = ase.io.read(stru_file, format='vasp')
            if kpoints_file is not None:
                from pymatgen.io.vasp import Kpoints

                kpoints = Kpoints.from_file(kpoints_file)
                obj._kpoints = tuple(int(k) for k in kpoints.kpts[0])
            if inputs_file is not None:
                incar = Incar.from_file(inputs_file)
                obj._inputs = incar.as_dict()
        else:
            raise NotImplementedError(f"Software '{software}' is not supported yet.")

        return obj


    @property
    def stru(self) -> Atoms:
        if self._stru is None:
            raise ValueError("Structure is not set.")
        return self._stru
    
    @property
    def pp_path(self) -> Path:
        if self._pp_path is None:
            raise ValueError("Pseudopotential path is not set.")
        return self._pp_path
    
    @property
    def orb_path(self) -> Path:
        if self._orb_path is None:
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
        folder.mkdir(parents=True, exist_ok=True)
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
