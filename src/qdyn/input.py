from pydantic import BaseModel, Field, field_validator
from typing import Literal, List, Optional, Any

import numpy as np

## Important!
# InputT: should contain minimal parameters exposed to users,
#         universal for all DFT codes
# paramters: str, in DFT code vanilla input format (for advanced users)

## load order:
# Default param template
# -> predefined params in InputT
# -> parameters string (overrides previous ones)


class BasicInputT(BaseModel):
    """Basic input parameters for QDYN calculations."""

    software: Literal['vasp', 'cp2k', 'siesta', 'abacus', 'openmx'] = 'vasp'
    plot: bool = False


class SchedulerConfigT(BaseModel):
    """Scheduler configuration (reserved for future use)."""

    pass


class NAMDInputT(BaseModel):
    nodes: Optional[int] = None

    md_dt: float = 1.0
    adiabatic_rep: bool = True
    surface_hopping: Literal['FSSH', 'DISH'] = 'DISH'
    nsample: int = 200
    ntraj: int = 200
    nelm: int = 10
    namdtime: int = 1_000_000  # 1 ns
    temperature: float = 300.0
    lhole: bool = False
    inibands: List[int]  # start from 1


class _PreNAMDInputAdvT(BaseModel):
    reorder: bool = False
    alle: bool = False
    ikpt: int = 1
    ispin: int = 1

    which_atoms: Optional[List[int]] = None
    cbar_labels: Optional[List[str]] = None

    @field_validator('which_atoms', mode='before')
    @classmethod
    def normalize_which_atoms(cls, value):
        if value is None:
            return None
        if isinstance(value, np.ndarray):
            return value.tolist()
        return value


class PreNAMDInputT(BaseModel):
    bmin: int | str = 'VBM'
    bmax: int | str = 'CBM'
    md_dt: float = 1.0
    adiabatic_rep: bool = True
    surface_hopping: Literal['FSSH', 'DISH'] = 'DISH'

    adv: _PreNAMDInputAdvT = _PreNAMDInputAdvT()


class NVTInputT(BaseModel):
    """Input parameters for NVT molecular dynamics."""

    nodes: Optional[int] = None

    kspacing: float = Field(0.04, description=r"K-point spacing in 2\pi \times 1/Å")
    md_thermostat: Literal['nhc', 'rescale_v'] = 'rescale_v'
    md_dt: float = Field(1.0, description="MD time step in fs")
    md_step: int = Field(1000, description="Number of MD steps")
    temp_begin: float = Field(300.0, description="Initial temperature in K")
    temp_end: float = Field(300.0, description="Final temperature in K")
    scf_thr: float = 1e-6

    parameters: str = ''


class NVEInputT(BaseModel):
    """Input parameters for NVE molecular dynamics."""

    nodes: Optional[int] = None

    kspacing: float = Field(0.04, description=r"K-point spacing in 2\pi \times 1/Å")

    # MD parameters
    md_dt: float = Field(1.0, description="MD time step in fs")
    md_step: int = Field(1000, description="Number of MD steps")
    scf_thr: float = 1e-6

    parameters: str = ''


class SCFInputT(BaseModel):
    """Input parameters for static SCF calculation."""

    nodes: Optional[int] = None

    kspacing: float = Field(0.04, description=r"K-point spacing in 2\pi \times 1/Å")

    # SCF-specific
    scf_thr: float = 1e-6

    # job control
    scf_step: int = Field(1000, description="Number of SCF frames to calculate")

    batch_size: int = Field(
        100,
        description="Number of frames per batch task. Smaller batches mean more parallel tasks.",
    )

    is_alle: bool = Field(False, description="Whether to use all-electron vasp")
    parameters: str = Field('', description="Additional INCAR parameters string")


class InputT(BaseModel):
    """Input parameters for QDYN workflow."""

    basic_input: BasicInputT
    scheduler_config: SchedulerConfigT
    nvt_input: Optional[NVTInputT] = None
    nve_input: Optional[NVEInputT] = None
    scf_input: Optional[SCFInputT] = None
    prenamd_input: Optional[PreNAMDInputT] = None
    namd_input: Optional[NAMDInputT] = None

    steps: List[Literal['nvt', 'nve', 'scf', 'pre_namd', 'namd']] = ['nvt']
    stru: Optional[str] = ''
    stru_format: str = 'vasp'


# deprecated
def grep_input_parameters(file_path: str) -> dict:
    """
    Extract parameters from a plain text file and return a dictionary.

    File format example:
        parameter_name = value1 value2 value3 ... # comments

    Args:
        file_path: Path to the text file

    Returns:
        dict: Dictionary mapping parameter names to parameter values
              - Single values are automatically converted to int/float/bool/str
              - Multiple values return a list, with each element automatically converted
    """
    result = {}

    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            # Remove leading and trailing whitespace
            line = line.strip()

            # Skip empty lines
            if not line:
                continue

            # Remove comments (content after #)
            if '#' in line:
                line = line[: line.index('#')].strip()

            # Skip lines with only comments
            if not line:
                continue

            # Parse parameter name and value
            if '=' in line:
                parts = line.split('=', 1)
                param_name = parts[0].strip()
                param_value_str = parts[1].strip() if len(parts) > 1 else ''

                if not param_name:
                    continue

                # Parse parameter values
                result[param_name] = _parse_value_string(param_value_str)

    return result


def _parse_value_string(value_str: str) -> Any:
    """
    Parse parameter value string and automatically convert types.

    Args:
        value_str: Parameter value string (may contain multiple space-separated values)

    Returns:
        - If single value: return int/float/bool/str
        - If multiple values: return a list, with each element automatically converted
    """
    if not value_str:
        return ''

    # Split multiple values
    values = value_str.split()

    # Parse each value
    parsed_values = [_parse_single_value(v) for v in values]

    # If only one value, return it directly; otherwise return a list
    if len(parsed_values) == 1:
        return parsed_values[0]
    return parsed_values


def _parse_single_value(value: str) -> Any:
    """
    Parse a single parameter value and automatically convert types.

    Args:
        value: Single parameter value string

    Returns:
        Converted value (int/float/bool/str)
    """
    # Try to convert to bool (supports various software boolean formats)
    # Supported formats: True/False, true/false, T/F, t/f, .TRUE./.FALSE., .true./.false.
    value_lower = value.lower()
    if value_lower in ('true', 't', '.true.'):
        return True
    if value_lower in ('false', 'f', '.false.'):
        return False

    # Try to convert to float first to preserve decimal values
    try:
        float_val = float(value)
        # If the float value is a whole number (e.g., 3.0), return as int
        if float_val.is_integer():
            return int(float_val)
        return float_val
    except ValueError:
        pass

    # Keep as str
    return value
