import io
import math
import os
import glob
from pathlib import Path
import shutil
from typing import Any, Dict, List, Tuple, Union

import numpy as np
from ase import Atoms
from pymatgen.io.vasp import Incar

from .calc_common import write_stru, read_stru
from .params import PSEUDO_POTENTIAL, STRU_FNAME_MAPPING, STRU_FORMAT_MAPPING
from .tools.pseuh import write_stru_pseuh


class DFTInputs:

    def __init__(
        self,
        software: str,
        structure: Atoms | None = None,
        pp_path: str | Path | None = None,
        orb_path: str | Path | None = None,
        kspacing: float | None = None,
        pseudo_h: bool = False,
        inputs_dict: dict | None = None,
        inputs_params: str = '',
    ):
        # init 
        self.allow_modify = True
        self._stru: Atoms | None = structure
        self._stru_extras: str | None = None
        self._pp_path = (Path(pp_path).expanduser().resolve() 
                         if pp_path is not None else None)
        self._orb_path = (Path(orb_path).expanduser().resolve() 
                          if orb_path is not None else None)
        self._kpoints: tuple[int, int, int] | None = None
        self._pseudoh: bool = pseudo_h
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
            self.update_inputs(inputs_dict, inputs_params)


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
                obj._stru = read_stru('vasp', stru_file)
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
    
    @property
    def stru_extras(self) -> str | None:
        if self._stru_extras is None:
            tmp = []
            if self.software == 'openmx':
                for key, value in self.inputs.items():
                    if isinstance(value, list):
                        tmp.append(f'<{key}')
                        tmp.extend(value)
                        tmp.append(f'{key}>')
                    else:
                        tmp.append(f'{key}    {value}')
                self._stru_extras = '\n'.join(tmp)
        return self._stru_extras
    
    def update_stru_extras(self) -> str | None:
        self._stru_extras = None
        return self.stru_extras
    
    def calc_kpoints(self, kspacing: float) -> tuple[int, int, int]:
        rec_cell = self.stru.cell.reciprocal().array

        kpoints = []
        for i in range(3):
            length = np.linalg.norm(rec_cell[i])
            nk = max(1, length / kspacing)
            kpoints.append(nk)
        kpoints = symmetric_kpoints(self.stru, kpoints)

        return tuple(kpoints) # type: ignore
    
    def update_inputs(self, inputs_dict: dict, inputs_params: str = '') -> None:
        if self.software == 'vasp':
            if self._inputs is not None:
                inputs_base = self._inputs
                inputs_base.update(inputs_dict)
            else:
                inputs_base = inputs_dict
            incar = Incar.from_dict(inputs_base)
            if inputs_params:
                incar_append = Incar.from_str(inputs_params)
                incar.update(incar_append)

            if self.gamma:
                incar['KPAR'] = 1
            else:
                kx, ky, kz = self.kpoints
                nk = 1 + kx//2 + ky//2 + kz//2 + (kx*ky*kz)//2 # Gamma-centered
                incar['KPAR'] = (8 if nk >= 8 
                                   else 4 if nk >= 4 
                                   else 2 if nk >= 2 
                                   else 1)
            
            self._inputs = incar.as_dict()
        elif self.software == 'openmx':
            if self._inputs is not None:
                inputs_base = self._inputs
                inputs_base.update(inputs_dict)
            else:
                inputs_base = inputs_dict
            if inputs_params:
                with io.StringIO(inputs_params) as s:
                    inputs_append = parse_openmx_dat(s)
                inputs_base.update(inputs_append)
            # Standardize default fields and stru fields
            if self._pp_path != self._orb_path:
                raise ValueError("Orbital path and pp path must be the same for OpenMX.")
            inputs_base['data.path'] = self._pp_path
            inputs_base.pop('system.currentdirectory', None)
            inputs_base['system.name'] = 'qdyn'
            kx, ky, kz = self.kpoints
            inputs_base['scf.kgrid'] = f'{kx} {ky} {kz}'
            inputs_base.pop('species.number', None)
            inputs_base.pop('definition.of.atomic.species', None)
            inputs_base.pop('atoms.number', None)
            inputs_base.pop('atoms.speciesandcoordinates.unit', None)
            inputs_base.pop('atoms.speciesandcoordinates', None)
            inputs_base.pop('atoms.unitvectors.unit', None)
            inputs_base.pop('atoms.unitvectors', None)
            inputs_base.pop('md.init.velocity', None)
            inputs_base.pop('md.fixed.xyz', None)
            
            self._inputs = inputs_base
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
        if self._pseudoh:
            write_stru_pseuh(
                software,
                folder,
                self.stru,
                self.pp_path,
                self.stru_extras
            )
        else:
            if stru:
                write_stru(folder / STRU_FNAME_MAPPING[software], 
                        self.stru,
                        STRU_FORMAT_MAPPING[software], 
                        self.stru_extras)
            if pp:
                self.write_pp(software, folder)

    def write_inputs(self, software: str, folder: Path):
        if software == 'vasp':
            incar = Incar.from_dict(self.inputs)
            incar.write_file(folder / 'INCAR')
        elif software == 'openmx':
            pass
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
        elif software == 'openmx':
            pass
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
                    pp_file = self.pp_path / PSEUDO_POTENTIAL[software][s] / "POTCAR"
                    if not pp_file.is_file():
                        raise FileNotFoundError(
                            f"POTCAR for element {s} not found in {self.pp_path}.")
                    with open(pp_file, 'r') as inf:
                        shutil.copyfileobj(inf, outf)
        elif software == 'openmx':
            pass
        else:
            raise NotImplementedError(f"Software '{software}' is not supported yet.")


def parse_openmx_dat(params: io.StringIO, inner: bool = False) -> dict:
    inputs_dict = {}
    inputs_list = []
    while True:
        line = params.readline()
        if not line:
            break
        line = line.strip()
        if line.startswith('#'):
            continue
        elif line.startswith('<'):
            block = line[1:].lower()
            outputs_list = parse_openmx_dat(params, inner=True)[0]
            inputs_dict[block] = outputs_list
        elif line.endswith('>'):
            return {0: inputs_list}
        elif inner:
            inputs_list.append(line)
        else:
            try:
                parts = line.split()
                inputs_dict[parts[0].lower()] = '  '.join(parts[1:])
            except Exception as e:
                raise ValueError(f'Failed to parse openmx-dat with {e}')
            
    return inputs_dict

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
