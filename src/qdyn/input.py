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

# ---------------------------------------------------------------------------
# Reusable json_schema_extra constants for UI metadata
# ---------------------------------------------------------------------------
SCF_THR_OPTIONS = [1e-4, 1e-5, 1e-6, 1e-7, 1e-8]
HIDDEN_FIELD: dict[str, Any] = {"hidden": True}
ADVANCED_GROUP: dict[str, Any] = {"group": "advanced"}


class BasicInputT(BaseModel):
    """Basic input parameters for QDYN calculations."""

    software: Literal['vasp', 'cp2k', 'siesta', 'abacus', 'openmx'] = 'vasp'
    plot: bool = False


class SchedulerConfigT(BaseModel):
    """Scheduler configuration (reserved for future use)."""

    pass


class NAMDInputT(BaseModel):
    nodes: Optional[int] = Field(
        default=None,
        json_schema_extra=HIDDEN_FIELD,
    )

    md_dt: float = Field(
        1.0,
        ge=0.1, le=10,
        description="MD time step in fs",
        json_schema_extra={"precision": 2},
    )
    adiabatic_rep: bool = Field(True, description="Whether to use adiabatic representation")
    surface_hopping: Literal['FSSH', 'DISH'] = Field(
        'DISH', description="Surface hopping method",
    )
    nsample: int = Field(200, ge=1, le=10000, description="Number of sampled initial conditions")
    ntraj: int = Field(200, ge=1, le=10000, description="Number of trajectories to propagate")
    nelm: int = Field(10, ge=1, le=1000, description="Number of electronic substeps")
    namdtime: int = Field(
        1_000_000,
        ge=1000,
        description="Total number of NAMD time steps",
        json_schema_extra={"step": 100000},
    )
    temperature: float = Field(
        300.0,
        ge=1, le=10000,
        description="Simulation temperature in K",
        json_schema_extra={"precision": 1},
    )
    lhole: bool = Field(False, description="Whether to simulate hole dynamics")
    inibands: List[int] = Field(
        default_factory=lambda: [1, 2, 3, 4],
        description="Initial bands, 1-based, comma-separated in UI",
        json_schema_extra={
            "widget": "comma-separated-integers",
            "placeholder": "e.g. 1,2,3,4",
            "default": [1, 2, 3, 4],
        },
    )


class _PreNAMDInputAdvT(BaseModel):
    reorder: bool = Field(False, description="Whether to reorder bands before post-processing")
    alle: bool = Field(False, description="Whether to use all-electron data in pre-processing")
    ikpt: int = Field(1, ge=1, description="K-point index starting from 1", json_schema_extra={"step": 1})
    ispin: int = Field(
        1, ge=1, le=2,
        description="Spin channel index starting from 1",
        json_schema_extra={"step": 1},
    )

    which_atoms: Optional[List[int]] = Field(
        default=None,
        description="Optional atom indices to project, comma-separated in UI",
        json_schema_extra={"widget": "comma-separated-integers", "placeholder": "e.g. 1,2,5"},
    )
    cbar_labels: Optional[List[str]] = Field(
        default=None,
        description="Optional colorbar labels, comma-separated in UI",
        json_schema_extra={"widget": "comma-separated-strings", "placeholder": "e.g. CBM,VBM,DEFECT"},
    )

    @field_validator('which_atoms', mode='before')
    @classmethod
    def normalize_which_atoms(cls, value):
        if value is None:
            return None
        if isinstance(value, np.ndarray):
            return value.tolist()
        return value


class PreNAMDInputT(BaseModel):
    bmin: int | str = Field(
        'VBM',
        description="Lower band index, accepts integer or expressions like VBM-2",
        json_schema_extra={"widget": "band-input", "placeholder": "e.g. VBM, VBM-2, 10"},
    )
    bmax: int | str = Field(
        'CBM',
        description="Upper band index, accepts integer or expressions like CBM+4",
        json_schema_extra={"widget": "band-input", "placeholder": "e.g. CBM, CBM+4, 20"},
    )
    md_dt: float = Field(
        1.0,
        ge=0.1, le=10,
        description="MD time step in fs",
        json_schema_extra={"precision": 2},
    )
    adiabatic_rep: bool = Field(True, description="Whether to use adiabatic representation")
    surface_hopping: Literal['FSSH', 'DISH'] = Field(
        'DISH', description="Surface hopping method",
    )

    adv: _PreNAMDInputAdvT = Field(
        default_factory=_PreNAMDInputAdvT,
        json_schema_extra={"group": "advanced"},
    )


class NVTInputT(BaseModel):
    """Input parameters for NVT molecular dynamics."""

    nodes: Optional[int] = Field(
        default=None,
        json_schema_extra=HIDDEN_FIELD,
    )

    kspacing: float = Field(
        0.04,
        ge=0.01, le=1,
        description="K-point spacing in 2π × 1/Å",
        json_schema_extra={"step": 0.01, "precision": 3},
    )
    md_thermostat: Literal['nhc', 'rescale_v'] = Field(
        'rescale_v', description="MD thermostat method",
    )
    md_dt: float = Field(
        1.0,
        ge=0.1, le=10,
        description="MD time step in fs",
        json_schema_extra={"step": 0.5, "precision": 1},
    )
    md_step: int = Field(
        1000,
        ge=100, le=100000,
        description="Number of MD steps",
        json_schema_extra={"step": 500},
    )
    temp_begin: float = Field(
        300.0,
        ge=1, le=10000,
        description="Initial temperature in K",
        json_schema_extra={"step": 50, "precision": 1},
    )
    temp_end: float = Field(
        300.0,
        ge=1, le=10000,
        description="Final temperature in K",
        json_schema_extra={"step": 50, "precision": 1},
    )
    scf_thr: float = Field(
        1e-6,
        ge=1e-8, le=1e-4,
        description="Electronic convergence criterion (eV)",
        json_schema_extra={"widget": "exp-select", "options": SCF_THR_OPTIONS},
    )

    parameters: str = Field(
        '',
        description="Additional INCAR parameters string",
        json_schema_extra={**ADVANCED_GROUP, "placeholder": "e.g. ENCUT = 520\\nISYM = 0"},
    )


class NVEInputT(BaseModel):
    """Input parameters for NVE molecular dynamics."""

    nodes: Optional[int] = Field(
        default=None,
        json_schema_extra=HIDDEN_FIELD,
    )

    kspacing: float = Field(
        0.04,
        ge=0.01, le=1,
        description="K-point spacing in 2π × 1/Å",
        json_schema_extra={"step": 0.01, "precision": 3},
    )

    # MD parameters
    md_dt: float = Field(
        1.0,
        ge=0.1, le=10,
        description="MD time step in fs",
        json_schema_extra={"step": 0.5, "precision": 1},
    )
    md_step: int = Field(
        1000,
        ge=100, le=100000,
        description="Number of MD steps",
        json_schema_extra={"step": 500},
    )
    scf_thr: float = Field(
        1e-6,
        ge=1e-8, le=1e-4,
        description="Electronic convergence criterion (eV)",
        json_schema_extra={"widget": "exp-select", "options": SCF_THR_OPTIONS},
    )

    parameters: str = Field(
        '',
        description="Additional INCAR parameters string",
        json_schema_extra={**ADVANCED_GROUP, "placeholder": "e.g. ENCUT = 520\\nISYM = 0"},
    )


class SCFInputT(BaseModel):
    """Input parameters for static SCF calculation."""

    nodes: Optional[int] = Field(
        default=None,
        json_schema_extra=HIDDEN_FIELD,
    )

    kspacing: float = Field(
        0.04,
        ge=0.01, le=1,
        description="K-point spacing in 2π × 1/Å",
        json_schema_extra={"step": 0.01, "precision": 3},
    )

    # SCF-specific
    scf_thr: float = Field(
        1e-6,
        ge=1e-8, le=1e-4,
        description="Electronic convergence criterion (eV)",
        json_schema_extra={"widget": "exp-select", "options": SCF_THR_OPTIONS},
    )

    # job control
    scf_step: int = Field(
        1000,
        ge=1, le=10000,
        description="Number of SCF frames to calculate",
        json_schema_extra={"step": 100},
    )

    batch_size: int = Field(
        100,
        ge=1, le=500,
        description="Number of frames per batch task. Smaller batches mean more parallel tasks.",
        json_schema_extra={"step": 10},
    )

    is_alle: bool = Field(False, description="Whether to use all-electron vasp")
    parameters: str = Field(
        '',
        description="Additional INCAR parameters string",
        json_schema_extra={**ADVANCED_GROUP, "placeholder": "e.g. ENCUT = 520\\nISYM = 0"},
    )


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
