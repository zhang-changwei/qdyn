import re

from pydantic import BaseModel, Field, field_validator
from typing import Literal, List, Any

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
    nodes: int | None = Field(
        default=None,
        description="Number of compute nodes. Leave empty to use qdyn config default.",
        json_schema_extra={
            "group": "advanced",
            "step": 1,
            "placeholder": "Auto (from config)",
        },
    )

    md_dt: float = Field(
        1.0,
        ge=1e-6,
        le=1000,
        description="MD time step in fs",
        json_schema_extra={"step": 0.01, "precision": 4},
    )
    adiabatic_rep: bool = Field(
        True, description="Whether to use adiabatic representation"
    )
    surface_hopping: Literal['FSSH', 'DISH'] = Field(
        'DISH',
        description="Surface hopping method",
    )
    nsample: int = Field(
        200, ge=1, le=10000, description="Number of sampled initial conditions"
    )
    ntraj: int = Field(
        200, ge=1, le=10000, description="Number of trajectories to propagate"
    )
    nelm: int = Field(10, ge=1, le=1000, description="Number of electronic substeps")
    namdtime: int = Field(
        1_000_000,
        ge=1,
        description="Total number of NAMD time steps",
        json_schema_extra={"step": 100000},
    )
    temperature: float = Field(
        300.0,
        ge=0.0,
        description="Simulation temperature in K",
        json_schema_extra={"step": 1.0, "precision": 3},
    )
    lhole: bool = Field(False, description="Whether to simulate hole dynamics")
    inibands: List[int] = Field(
        description="Initial band indices within the bmin–bmax window (1 = bmin, 2 = bmin+1, ...)",
        json_schema_extra={
            "widget": "comma-separated-integers",
            "placeholder": "e.g. 2,3,4 (1=bmin, 2=bmin+1, ...)",
        },
    )


class _PreNAMDInputAdvT(BaseModel):
    reorder: bool = Field(
        False, description="Whether to reorder bands before post-processing"
    )
    alle: bool = Field(
        False, description="Whether to use all-electron data in pre-processing"
    )
    ikpt: int = Field(
        1,
        ge=1,
        description="K-point index starting from 1",
        json_schema_extra={"step": 1},
    )
    ispin: int = Field(
        1,
        ge=1,
        le=2,
        description="Spin channel index starting from 1",
        json_schema_extra={"step": 1},
    )

    which_atoms: List[int] | None = Field(
        default=None,
        description="Optional atom indices to project, comma-separated in UI",
        json_schema_extra={
            "widget": "comma-separated-integers",
            "placeholder": "e.g. 1,2,5",
        },
    )
    cbar_labels: List[str] | None = Field(
        default=None,
        description="Optional colorbar labels, comma-separated in UI",
        json_schema_extra={
            "widget": "comma-separated-strings",
            "placeholder": "e.g. CBM,VBM,DEFECT",
        },
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
        json_schema_extra={
            "widget": "band-input",
            "placeholder": "e.g. VBM, VBM-2, 10",
        },
    )
    bmax: int | str = Field(
        'CBM',
        description="Upper band index, accepts integer or expressions like CBM+4",
        json_schema_extra={
            "widget": "band-input",
            "placeholder": "e.g. CBM, CBM+4, 20",
        },
    )
    md_dt: float = Field(
        1.0,
        ge=1e-6,
        le=1000,
        description="MD time step in fs",
        json_schema_extra={"step": 0.01, "precision": 4},
    )
    adiabatic_rep: bool = Field(
        True, description="Whether to use adiabatic representation"
    )
    surface_hopping: Literal['FSSH', 'DISH'] = Field(
        'DISH',
        description="Surface hopping method",
    )

    adv: _PreNAMDInputAdvT = Field(
        default_factory=_PreNAMDInputAdvT,
        json_schema_extra={"group": "advanced"},
    )


class NVTInputT(BaseModel):
    """Input parameters for NVT molecular dynamics."""

    nodes: int | None = Field(
        default=None,
        description="Number of compute nodes. Leave empty to use qdyn config default.",
        json_schema_extra={
            "group": "advanced",
            "step": 1,
            "placeholder": "Auto (from config)",
        },
    )

    kspacing: float = Field(
        0.04,
        ge=1e-4,
        le=10.0,
        description="K-point spacing in 2π × 1/Å",
        json_schema_extra={"step": 0.001, "precision": 4},
    )
    md_thermostat: Literal['nhc', 'rescale_v'] = Field(
        'rescale_v',
        description="MD thermostat method",
    )
    md_dt: float = Field(
        1.0,
        ge=1e-6,
        le=1000,
        description="MD time step in fs",
        json_schema_extra={"step": 0.01, "precision": 4},
    )
    md_step: int = Field(
        1000,
        ge=1,
        le=10000000,
        description="Number of MD steps",
        json_schema_extra={"step": 500},
    )
    temp_begin: float = Field(
        300.0,
        ge=0.0,
        description="Initial temperature in K",
        json_schema_extra={"step": 1.0, "precision": 3},
    )
    temp_end: float = Field(
        300.0,
        ge=0.0,
        description="Final temperature in K",
        json_schema_extra={"step": 1.0, "precision": 3},
    )
    scf_thr: float = Field(
        1e-6,
        ge=1e-12,
        le=1.0,
        description="Electronic convergence criterion (eV)",
        json_schema_extra={"widget": "log-step"},
    )

    constraint_layers: Optional[str] = Field(
        default=None,
        description="Number of surface layers to fix (counting from 1 from bottom to top.). Leave empty for no constraints. Not useful when the structure file has already included constraints, which will be applied directly. Format: e.g. '1-3 5' means fixing layers 1 to 3 and layer 5 from bottom to top.",
        json_schema_extra=ADVANCED_GROUP,
    )
    layer_direction: Optional[
        Literal['000', '001', '010', '011', '100', '101', '110', '111']
    ] = Field(
        default=None,
        description="Miller indices of the crystal surface. Required if constraint_layers is set.",
        json_schema_extra=ADVANCED_GROUP,
    )
    total_layers: Optional[int] = Field(
        default=None,
        description="Total number of surface layers. Required if constraint_layers is set, for correct constraint application. Leave empty for no constraints.",
        json_schema_extra=ADVANCED_GROUP,
    )

    parameters: str = Field(
        '',
        description="Additional INCAR parameters string",
        json_schema_extra={
            **ADVANCED_GROUP,
            "widget": "textarea",
            "placeholder": "e.g. ENCUT = 520\nISYM = 0",
        },
    )


class NVEInputT(BaseModel):
    """Input parameters for NVE molecular dynamics."""

    nodes: int | None = Field(
        default=None,
        description="Number of compute nodes. Leave empty to use qdyn config default.",
        json_schema_extra={
            "group": "advanced",
            "step": 1,
            "placeholder": "Auto (from config)",
        },
    )

    kspacing: float = Field(
        0.04,
        ge=1e-4,
        le=10.0,
        description="K-point spacing in 2π × 1/Å",
        json_schema_extra={"step": 0.001, "precision": 4},
    )

    # MD parameters
    md_dt: float = Field(
        1.0,
        ge=1e-6,
        le=1000,
        description="MD time step in fs",
        json_schema_extra={"step": 0.01, "precision": 4},
    )
    md_step: int = Field(
        1000,
        ge=1,
        le=10000000,
        description="Number of MD steps",
        json_schema_extra={"step": 500},
    )
    scf_thr: float = Field(
        1e-6,
        ge=1e-12,
        le=1.0,
        description="Electronic convergence criterion (eV)",
        json_schema_extra={"widget": "log-step"},
    )

    constraint_layers: Optional[str] = Field(
        default=None,
        description="Number of surface layers to fix (counting from 1 from bottom to top.). Leave empty for no constraints. Not useful when the structure file has already included constraints, which will be applied directly. Format: e.g. '1-3 5' means fixing layers 1 to 3 and layer 5 from bottom to top.",
        json_schema_extra=ADVANCED_GROUP,
    )
    layer_direction: Optional[
        Literal['000', '001', '010', '011', '100', '101', '110', '111']
    ] = Field(
        default=None,
        description="Miller indices of the crystal surface. Required if constraint_layers is set.",
        json_schema_extra=ADVANCED_GROUP,
    )
    total_layers: Optional[int] = Field(
        default=None,
        description="Total number of surface layers. Required if constraint_layers is set, for correct constraint application. Leave empty for no constraints.",
        json_schema_extra=ADVANCED_GROUP,
    )

    parameters: str = Field(
        '',
        description="Additional INCAR parameters string",
        json_schema_extra={
            **ADVANCED_GROUP,
            "widget": "textarea",
            "placeholder": "e.g. ENCUT = 520\nISYM = 0",
        },
    )


class SCFInputT(BaseModel):
    """Input parameters for static SCF calculation."""

    nodes: int | None = Field(
        default=None,
        description="Number of compute nodes. Leave empty to use qdyn config default.",
        json_schema_extra={
            "group": "advanced",
            "step": 1,
            "placeholder": "Auto (from config)",
        },
    )

    kspacing: float = Field(
        0.04,
        ge=1e-4,
        le=10.0,
        description="K-point spacing in 2π × 1/Å",
        json_schema_extra={"step": 0.001, "precision": 4},
    )

    # SCF-specific
    scf_thr: float = Field(
        1e-6,
        ge=1e-12,
        le=1.0,
        description="Electronic convergence criterion (eV)",
        json_schema_extra={"widget": "log-step"},
    )

    # job control
    scf_step: int = Field(
        1000,
        ge=1,
        le=10000000,
        description="Number of SCF frames to calculate",
        json_schema_extra={"step": 100},
    )

    batch_size: int = Field(
        100,
        ge=1,
        le=10000,
        description="Number of frames per batch task. Smaller batches mean more parallel tasks.",
        json_schema_extra={"step": 10},
    )

    is_alle: bool = Field(False, description="Whether to use all-electron vasp")
    parameters: str = Field(
        '',
        description="Additional INCAR parameters string",
        json_schema_extra={
            **ADVANCED_GROUP,
            "widget": "textarea",
            "placeholder": "e.g. ENCUT = 520\nISYM = 0",
        },
    )


class InputT(BaseModel):
    """Input parameters for QDYN workflow."""

    basic_input: BasicInputT
    scheduler_config: SchedulerConfigT
    nvt_input: NVTInputT | None = None
    nve_input: NVEInputT | None = None
    scf_input: SCFInputT | None = None
    prenamd_input: PreNAMDInputT | None = None
    namd_input: NAMDInputT | None = None

    steps: List[Literal['nvt', 'nve', 'scf', 'pre_namd', 'namd']] = ['nvt']
    stru: str = ''
    stru_format: str = 'vasp'
    stru_hash: str = ''

    @field_validator('stru_hash')
    @classmethod
    def validate_stru_hash(cls, v: str) -> str:
        """Ensure stru_hash is either empty or a valid 32-char hex string (MD5)."""
        from .params import HASH_PATTERN

        if v and not HASH_PATTERN.match(v):
            raise ValueError(
                'stru_hash must be a 32-character lowercase hex string (MD5 digest)'
            )
        return v


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
