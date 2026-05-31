import re

from pydantic import BaseModel, Field, field_validator, PositiveInt, AfterValidator
from typing import Literal, List, Any, Annotated

import numpy as np

from .params import NEQUIP_PRETRAINED_MODELS_TYPE
from .params import MACE_PRETRAINED_MODELS_TYPE
from .params import HAMGNN_PRETRAINED_MODELS_TYPE
from .params import HASH_PATTERN

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


def validate_md5_hash(v: str) -> str:
    """Ensure string is either empty or a valid 32-char hex string (MD5)."""
    if v and not HASH_PATTERN.match(v):
        raise ValueError('must be a 32-character lowercase hex string (MD5 digest)')
    return v

MD5HashStr = Annotated[str, AfterValidator(validate_md5_hash)]


class BasicInputT(BaseModel):
    """Basic input parameters for QDYN calculations."""

    # deprecated
    software: Literal['vasp', 'cp2k', 'siesta', 'abacus', 'openmx'] = 'vasp'
    plot: bool = False

class SchedulerConfigT(BaseModel):
    """Scheduler configuration (reserved for future use)."""

    pass



class DispersionInputT(BaseModel):
    algo: Literal['dftd2', 'dftd3'] = 'dftd3'
    damping: Literal['zero', 'bj', 'zerom', 'bjm'] = 'bj'
    xc: str = 'pbe'
    cutoff: float = Field(
        default=40.0,
        ge=0.0,
        description=("Cutoff distance for dispersion interactions in Bohr.\n"
                     "Set to 0.0 to use default values in DFT codes."),
    )

class DFTBaseInputT(BaseModel):
    '''Base class for DFT input parameters, containing common fields.'''

    nodes: PositiveInt | None = Field(
        default=None,
        le=8,
        description="Number of compute nodes. Leave empty to use qdyn config default.",
        json_schema_extra={
            "group": "advanced",
            "step": 1,
            "placeholder": "Auto (from config)",
        },
    )

    kspacing: float = Field(
        default=0.04,
        ge=1e-4,
        le=10.0,
        description="K-point spacing in 2π × 1/Å",
        json_schema_extra={"step": 0.001, "precision": 4},
    )

    scf_thr: float = Field(
        default=1e-6,
        ge=1e-12,
        le=1.0,
        description=("Electronic convergence criterion (eV). "
        " Hint: The unit is Hartree when using OPENMX."),
        json_schema_extra={"widget": "log-step"},
    )

    parameters: str = Field(
        default='',
        description="Additional INCAR parameters string",
        json_schema_extra={
            **ADVANCED_GROUP,
            "widget": "textarea",
            "placeholder": "e.g. ENCUT = 520\nISYM = 0",
        },
    )

class NequipInputT(BaseModel):
    version: str = 'v0'
    use_gpu: bool = False
    use_pretrained_model: bool = False
    model_name: NEQUIP_PRETRAINED_MODELS_TYPE | Literal[''] = ''
    model_hash: MD5HashStr = ''
    energy_unit: Literal['eV', 'Ry', 'Ha'] = 'eV'
    length_unit: Literal['Ang', 'Bohr'] = 'Ang'
    dispersion: DispersionInputT | None = None

class MACEInputT(BaseModel):
    version: str = 'v0'
    use_gpu: bool = False
    use_pretrained_model: bool = True
    model_name: MACE_PRETRAINED_MODELS_TYPE | Literal[''] = ''
    model_hash: MD5HashStr = ''
    default_dtype: Literal['float32', 'float64'] = 'float32'
    dispersion: DispersionInputT | None = None

class _HamGNNInputAdvT(BaseModel):
    legacy_edge_update: bool = False
    cutoff_func: str = "cos"
    edge_sh_normalization: str = "component"
    edge_sh_normalize: bool = True
    num_radial: int = 64
    num_types: int = 96
    rbf_func: str = "bessel"
    set_features: bool = True
    radial_MLP: list[int] = [64, 64]
    use_corr_prod: bool = False
    correlation: int = 2
    num_hidden_features: int = 32
    use_kan: bool = False
    radius_scale: float = 1.01
    build_internal_graph: bool = False
    eigen_dtype: Literal['float32', 'float64'] = 'float64'

class HamGNNInputT(BaseModel):
    """Input parameters for HamGNN tight-binding Hamiltonian construction."""
    version: Literal['v2.1'] = 'v2.1'
    use_gpu: bool = False
    use_pretrained_model: bool = False
    model_name: HAMGNN_PRETRAINED_MODELS_TYPE | Literal[''] = ''
    model_hash: str = ''
    ham_type: Literal['abacus', 'openmx'] = 'openmx'
    nao_max: int = 26
    add_H0: bool = False
    batch_size: int = 32

    cutoff: float = 24.0
    irreps_edge_sh: str = "0e + 1o + 2e + 3o + 4e"
    irreps_node_features: str = "64x0e+32x1o+16x1e+8x2o+24x2e+8x3o+4x3e+4x4e"
    num_layers: int = 3

    kspacing: float = Field(
        default=0.04,
        ge=1e-4,
        le=10.0,
        description="K-point spacing in 2π × 1/Å",
        json_schema_extra={"step": 0.001, "precision": 4},
    )
    ecut: float = Field(
        default=150.0,
        ge=1.0,
        description="Energy cutoff (in Ry) for two-center integrals in LCAO."
    )

    adv: _HamGNNInputAdvT = Field(
        default_factory=_HamGNNInputAdvT,
        json_schema_extra={"group": "advanced"},
    )



class ScissorInputT(BaseModel):
    scissor_shift: float = Field(
        default=0.0,
        ge=0.0,
        description="Scissor shift value in eV",
    )
    scissor_bmin: PositiveInt = Field(
        description="Minimum band index for scissor operator (1 = bmin)",
        json_schema_extra={
            "step": 1,
            "placeholder": "e.g. 2 (1=bmin, 2=bmin+1, ...)",
        },
    )

class NAMDInputT(BaseModel):
    nodes: PositiveInt | None = Field(
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
    bmin: str = Field(
        'VBM',
        description="Lower band index, accepts integer or expressions like VBM-2",
        json_schema_extra={
            "widget": "band-input",
            "placeholder": "e.g. VBM, VBM-2, 10",
        },
    )
    bmax: str = Field(
        'CBM',
        description="Upper band index, accepts integer or expressions like CBM+4",
        json_schema_extra={
            "widget": "band-input",
            "placeholder": "e.g. CBM, CBM+4, 20",
        },
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
    scissor: ScissorInputT | None = None


class _PreNAMDInputAdvT(BaseModel):
    reorder: bool = Field(
        default=False, description="Whether to reorder bands before post-processing"
    )
    alle: bool = Field(
        default=False, description="Whether to use all-electron data in pre-processing"
    )
    ikpt: int = Field(
        default=1,
        ge=1,
        description="K-point index starting from 1",
        json_schema_extra={"step": 1},
    )
    ispin: int = Field(
        default=1,
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
    bmin: str = Field(
        'VBM-31',
        description="Lower band index, accepts integer or expressions like VBM-2",
        json_schema_extra={
            "widget": "band-input",
            "placeholder": "e.g. VBM, VBM-2, 10",
        },
    )
    bmax: str = Field(
        'CBM+31',
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



class SelDynInputT(BaseModel):
    constraint_layers: List[int] | None = Field(
        default=None,
        description="Number of surface layers to fix (counting from 1 from bottom to top.). "
        "Leave empty for no constraints. Not useful when the structure file has already "
        "included constraints, which will be applied directly. Format: e.g. '1-3 5' or "
        "[1,2,3,5] means fixing layers 1 to 3 and layer 5 from bottom to top.",
        json_schema_extra={
            **ADVANCED_GROUP,
            "widget": "text",
            "placeholder": "e.g. 1-3 5",
        },
    )
    layer_direction: (
        Literal['000', '001', '010', '011', '100', '101', '110', '111'] | None
    ) = Field(
        default=None,
        description="Miller indices of the crystal surface. Required if constraint_layers is set.",
        json_schema_extra=ADVANCED_GROUP,
    )
    total_layers: int | None = Field(
        default=None,
        description="Total number of surface layers. Required if constraint_layers is set, "
        "for correct constraint application. Leave empty for no constraints.",
        json_schema_extra=ADVANCED_GROUP,
    )

    @field_validator('constraint_layers', mode='before')
    @classmethod
    def parse_constraint_layers(cls, v: str | List[int] | None) -> List[int] | None:

        if v is None:
            return None
        if isinstance(v, list):
            return v

        stripped = v.strip()
        if stripped == '':
            return None

        result: List[int] = []
        for part in stripped.split():
            if '-' in part:
                start, end = map(int, part.split('-'))
                result.extend(range(start, end + 1))
            else:
                result.append(int(part))

        return sorted(set(result))

class ThermostatsInputT(BaseModel):
    rescale_v_nraise: int = Field(
        default=5,
        ge=1,
    )
    bussi_taut: float = Field(
        default=100.0,
        ge=1.0,
        description="Time constant for Bussi temperature coupling in fs",
    )
    nhc_tdamp: float = 40.0
    nhc_tchain: int = 1

class PseudoHInputT(BaseModel):
    """Pseudo-hydrogen configuration for surface passivation."""

    is_pseudo_h: bool = Field(
        default=False,
        description="Whether to apply pseudo-hydrogen passivation to surface atoms. "
        "Pseudo-H atoms must be present in the input POSCAR with H\\d{3} "
        "placeholder symbols (e.g. H050 for ZVAL=0.5).",
    )


class NVTInputT(BaseModel):
    """Input parameters for NVT molecular dynamics."""
    _comment: str = (
        "NVT simulations can be run for multiple rounds.\n"
        "Different thermostats and step counts can be set per round.\n"
        "- 1st round (Warmup): Recommend 'rescale_v' or 'bussi' thermostat\n"
        "    with a larger step count to steadily reach equilibrium.\n"
        "- Subsequent rounds (Production): Temperature fixed at 'temp_end'. \n"
        "    Recommend 'bussi' or 'nhc' thermostats with fewer steps \n"
        "    for correct ensemble sampling.\n"
        "- Convergence check enabled in Production rounds.\n"
        "    NVT completes once convergence is reached or round count is exhausted.\n"
    )

    thermostats_algo: list[Literal['rescale_v', 'bussi', 'nhc']] = Field(
        default=['rescale_v']*4,
    )
    md_thermostats: ThermostatsInputT = Field(
        default_factory=ThermostatsInputT,
        json_schema_extra={"group": "advanced"},
    )
    md_dt: float = Field(
        1.0,
        ge=1e-6,
        le=1000,
        description="MD time step in fs",
        json_schema_extra={"step": 0.01, "precision": 4},
    )
    md_step: list[PositiveInt] = Field(
        [1000, 500, 500, 500],
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
    log_every: PositiveInt = 10

    sel: SelDynInputT = Field(
        default_factory=SelDynInputT,
        json_schema_extra={"group": "advanced"},
    )

    pseudo_h: PseudoHInputT | None = Field(
        default=None,
        json_schema_extra={"group": "advanced"},
    )

    software: Literal['vasp', 'nequip', 'mace'] = 'vasp'

    calculator: DFTBaseInputT | NequipInputT | MACEInputT = Field(
        default_factory=DFTBaseInputT,
    )


class NVEInputT(BaseModel):
    """Input parameters for NVE molecular dynamics."""

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
    log_every: Literal[1] = 1

    sel: SelDynInputT = Field(
        default_factory=SelDynInputT,
        json_schema_extra={"group": "advanced"},
    )

    pseudo_h: PseudoHInputT | None = Field(
        default=None,
        json_schema_extra={"group": "advanced"},
    )

    software: Literal['vasp', 'nequip', 'mace'] = 'vasp'

    calculator: DFTBaseInputT | NequipInputT | MACEInputT = Field(
        default_factory=DFTBaseInputT,
    )


class SCFInputT(BaseModel):
    """Input parameters for static SCF calculation."""

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
    pseudo_h: PseudoHInputT | None = Field(
        default=None,
        json_schema_extra={"group": "advanced"},
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
    
    software: Literal['vasp', 'openmx', 'hamgnn'] = 'vasp'

    calculator: DFTBaseInputT | HamGNNInputT = Field(
        default_factory=DFTBaseInputT,
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

    steps: List[Literal['nvt', 'nve', 'scf', 'pre_namd', 'namd', 
                        'fused_scf_prenamd']] = ['nvt']
    stru: str = ''
    stru_format: str = 'vasp'
    stru_hash: MD5HashStr = ''
    plot: bool = False

    task_name: str | None = Field(
        default=None,
        max_length=50,
        description="Custom task display name. Defaults to structure formula if empty.",
        json_schema_extra=HIDDEN_FIELD,
    )

    @field_validator('task_name', mode='before')
    @classmethod
    def normalize_task_name(cls, v):
        """Strip whitespace, reject empty strings, and validate character set."""
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return None
            if not re.match(r'^[A-Za-z0-9_\-. ()/+\u4e00-\u9fff]+$', v):
                raise ValueError(
                    'Task name may only contain letters, digits, spaces, '
                    'hyphens, underscores, dots, parentheses, slashes, plus signs, '
                    'and Chinese characters'
                )
        return v

