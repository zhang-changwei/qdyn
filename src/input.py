from pydantic import BaseModel, Field
from typing import Literal, List, Optional, Any

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


class BasicCalInputT(BaseModel):
    """Basic calculation input parameters."""

    # Kpoints
    kspacing: float = Field()

    # Common parameters
    encut: float = 500.0

    # Parallelization
    ncore: int = 8
    kpar: int = 2

    # Additional parameters string (KEY=VALUE format)
    parameters: str = ''


# class NVEInputT(BaseModel):
#     nodes: Optional[int] = None
#     kspacing: float = 0.04
#     encut: float = 500
#     scf_thr: float = 1e-6
#     temp_begin: float = 300
#     temp_end: float = 300


# class SCFInputT(BaseModel):
#     nodes: Optional[int] = None
#     kspacing: float = 0.04
#     encut: float = 500
#     scf_thr: float = 1e-6


class PreNAMDInputT(BaseModel):
    pass


class SRInputT(BasicCalInputT):
    """Input parameters for structure relaxation."""

    # Relaxation parameters
    nsw: int = 100
    ibrion: int = 2
    isif: int = 2
    ediffg: float = -0.01

    # Electronic
    nelm: int = 90
    nelmin: int = 6
    scf_thr: float = 1e-6

    def to_vasp_incar(self) -> dict:
        """Convert to VASP INCAR parameters."""
        return {
            'ENCUT': self.encut,
            'EDIFF': self.scf_thr,
            'NSW': self.nsw,
            'IBRION': self.ibrion,
            'ISIF': self.isif,
            'EDIFFG': self.ediffg,
            'NELM': self.nelm,
            'NELMIN': self.nelmin,
            'NCORE': self.ncore,
            'KPAR': self.kpar,
        }


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


class NVEInputT(BasicCalInputT):
    """Input parameters for NVE molecular dynamics."""

    nodes: Optional[int] = None

    # MD parameters
    ibrion: int = 0
    isym: int = 0
    smass: float = -3.0  # -3 for NVE (microcanonical)
    potim: float = 1.0
    nsw: int = 5000
    nblock: int = 1

    # Electronic
    algo: str = 'Normal'
    nelm: int = 120
    nelmin: int = 4
    scf_thr: float = 1e-6

    def to_vasp_incar(self) -> dict:
        """Convert to VASP INCAR parameters."""
        return {
            'ENCUT': self.encut,
            'EDIFF': self.scf_thr,
            'POTIM': self.potim,
            'NSW': self.nsw,
            'NBLOCK': self.nblock,
            'SMASS': self.smass,
            'ALGO': self.algo,
            'NELM': self.nelm,
            'NELMIN': self.nelmin,
            'ISYM': self.isym,
            'IBRION': self.ibrion,
            'NCORE': self.ncore,
            'KPAR': self.kpar,
        }


class SCFInputT(BasicCalInputT):
    """Input parameters for static SCF calculation."""

    nodes: Optional[int] = None

    # SCF-specific
    nelm: int = 120
    scf_thr: float = 1e-6
    lorbit: int = 11
    # nedos: int = 2001

    def to_vasp_incar(self) -> dict:
        """Convert to VASP INCAR parameters."""
        return {
            'ENCUT': self.encut,
            'EDIFF': self.scf_thr,
            'NELM': self.nelm,
            'LORBIT': self.lorbit,
            'NCORE': self.ncore,
            'KPAR': self.kpar,
        }


class InputT(BaseModel):
    """Input parameters for QDYN workflow."""

    basic_input: BasicInputT
    scheduler_config: SchedulerConfigT
    nvt_input: NVTInputT
    nve_input: NVEInputT
    scf_input: SCFInputT

    steps: List[Literal['nvt', 'nve', 'scf', 'pre_namd', 'namd']] = ['nvt']


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
