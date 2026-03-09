from pydantic import BaseModel
from typing import Literal, List, Optional

class BasicInputT(BaseModel):
    software: Literal['vasp', 'cp2k', 'siesta', 'abacus', 'openmx'] = 'vasp'
    plot: bool = False

class SchedulerConfigT(BaseModel):
    pass

class NVTInputT(BaseModel):
    nodes: Optional[int] = None
    kspacing: float = 0.04
    encut: float = 500
    scf_thr: float = 1e-6
    temp_begin: float = 300
    temp_end: float = 300

    paramters: str = ''

class NVEInputT(BaseModel):
    nodes: Optional[int] = None
    kspacing: float = 0.04
    encut: float = 500
    scf_thr: float = 1e-6
    temp_begin: float = 300
    temp_end: float = 300

class SCFInputT(BaseModel):
    nodes: Optional[int] = None
    kspacing: float = 0.04
    encut: float = 500
    scf_thr: float = 1e-6

class PreNAMDInputT(BaseModel):
    pass

class InputT(BaseModel):
    basic_input: BasicInputT
    scheduler_config: SchedulerConfigT
    nvt_input: NVTInputT
    nve_input: NVEInputT
    scf_input: SCFInputT

    steps: List[Literal['nvt', 'nve', 'scf', 'pre_namd', 'namd']]
