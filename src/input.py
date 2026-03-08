from pydantic import BaseModel
from typing import Literal, List

class BasicInputT(BaseModel):
    software: Literal['vasp', 'cp2k', 'siesta', 'abacus', 'openmx'] = 'vasp'
    plot: bool = False

class SchedulerConfigT(BaseModel):
    pass

class NVTInputT(BaseModel):
    kspacing: float = 0.04
    encut: float = 500
    scf_thr: float = 1e-6
    temp_begin: float = 300
    temp_end: float = 300

    paramters: str = ''

class InputT(BaseModel):
    basic_input: BasicInputT
    scheduler_config: SchedulerConfigT
    nvt_input: NVTInputT

    steps: List[Literal['NVT', 'NVE']]
