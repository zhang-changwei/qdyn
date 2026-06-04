import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator, PositiveInt, AfterValidator
from typing import Literal, List, Any, Annotated

import numpy as np

from .params import NEQUIP_PRETRAINED_MODELS_TYPE
from .params import MACE_PRETRAINED_MODELS_TYPE
from .params import HAMGNN_PRETRAINED_MODELS_TYPE
from .params import HAMGNN_PRETRAINED_CONFIGS
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


class SchedulerConfigT(BaseModel):
    """Scheduler configuration (reserved for future use)."""

    pass



class DispersionInputT(BaseModel):
    algo: Literal['dftd2', 'dftd3'] = Field(
        default='dftd3',
        description='Dispersion correction algorithm',
    )
    damping: Literal['zero', 'bj', 'zerom', 'bjm'] = Field(
        default='bj',
        description='Damping function for dispersion correction',
    )
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
        description=("Electronic convergence criterion. "
                     "Unit: eV (VASP), Hartree (OpenMX), unitless (ABACUS)."),
        json_schema_extra={"widget": "log-step"},
    )

    xc: Literal['PBE', 'PBEsol', 'PW91', 'HSE06', 'Not above'] = Field(
        default='PBE',
        description="Exchange-correlation functional type."
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
    energy_unit: Literal['eV', 'Ry', 'Ha'] = Field(
        default='eV',
        description='Energy unit of the training dataset'
    )
    length_unit: Literal['Ang', 'Bohr'] = Field(
        default='Ang',
        description='Length unit of the training dataset'
    )
    dispersion: DispersionInputT | None = None

class MACEInputT(BaseModel):
    version: str = 'v0'
    use_gpu: bool = False
    use_pretrained_model: bool = True
    model_name: MACE_PRETRAINED_MODELS_TYPE | Literal[''] = ''
    model_hash: MD5HashStr = ''
    default_dtype: Literal['float32', 'float64'] = Field(
        default='float32',
        description='numeric precision of the MACE model',
    )
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
    eigen_dtype: Literal['float32', 'float64'] = Field(
        default='float64',
        description='Numeric precision for eigenvalue solver',
    )

class HamGNNInputT(BaseModel):
    """Input parameters for HamGNN tight-binding Hamiltonian construction."""
    model_config = ConfigDict(json_schema_extra={
        "x-config-import": {
            "format": "yaml",
            "maxBytes": 262144,
            "hint": "Drop HamGNN config.yaml here to auto-fill parameters",
            "set": {"use_pretrained_model": False, "model_name": ""},
            "mapping": {
                "output_nets.HamGNN_out.ham_type": "ham_type",
                "output_nets.HamGNN_out.nao_max": "nao_max",
                "output_nets.HamGNN_out.add_H0": "add_H0",
                "representation_nets.HamGNN_pre.cutoff": "cutoff",
                "representation_nets.HamGNN_pre.irreps_edge_sh": "irreps_edge_sh",
                "representation_nets.HamGNN_pre.irreps_node_features": "irreps_node_features",
                "representation_nets.HamGNN_pre.num_layers": "num_layers",
                "representation_nets.HamGNN_pre.cutoff_func": "adv.cutoff_func",
                "representation_nets.HamGNN_pre.edge_sh_normalization": "adv.edge_sh_normalization",
                "representation_nets.HamGNN_pre.edge_sh_normalize": "adv.edge_sh_normalize",
                "representation_nets.HamGNN_pre.num_radial": "adv.num_radial",
                "representation_nets.HamGNN_pre.num_types": "adv.num_types",
                "representation_nets.HamGNN_pre.rbf_func": "adv.rbf_func",
                "representation_nets.HamGNN_pre.set_features": "adv.set_features",
                "representation_nets.HamGNN_pre.radial_MLP": "adv.radial_MLP",
                "representation_nets.HamGNN_pre.use_corr_prod": "adv.use_corr_prod",
                "representation_nets.HamGNN_pre.correlation": "adv.correlation",
                "representation_nets.HamGNN_pre.num_hidden_features": "adv.num_hidden_features",
                "representation_nets.HamGNN_pre.use_kan": "adv.use_kan",
                "representation_nets.HamGNN_pre.radius_scale": "adv.radius_scale",
                "representation_nets.HamGNN_pre.build_internal_graph": "adv.build_internal_graph",
                "representation_nets.HamGNN_pre.legacy_edge_update": "adv.legacy_edge_update",
            }
        },
        "x-pretrained-overrides": HAMGNN_PRETRAINED_CONFIGS,
    })

    version: Literal['v2.1'] = Field(
        default='v2.1',
        description='HamGNN model version',
    )
    use_gpu: bool = False
    use_pretrained_model: bool = False
    model_name: HAMGNN_PRETRAINED_MODELS_TYPE | Literal[''] = ''
    model_hash: str = ''
    ham_type: Literal['abacus', 'openmx'] = Field(
        default='openmx',
        json_schema_extra={"x-disabled-when": {"use_pretrained_model": True}},
    )
    nao_max: Literal[13, 14, 19, 20, 26] = Field(
        default=26,
        description="Maximum number of NAOs per atom in the Hamiltonian.",
        json_schema_extra={"x-disabled-when": {"use_pretrained_model": True}},
    )
    add_H0: bool = Field(
        default=False,
        json_schema_extra={"x-disabled-when": {"use_pretrained_model": True}},
    )
    batch_size: int = Field(
        default=16,
        ge=1,
        description="Number of structures per batch for HamGNN inference.",
        json_schema_extra={"step": 8},
    )
    cutoff: float = Field(
        default=24.0,
        json_schema_extra={"x-disabled-when": {"use_pretrained_model": True}},
    )
    irreps_edge_sh: str = Field(
        default="0e + 1o + 2e + 3o + 4e",
        json_schema_extra={"x-disabled-when": {"use_pretrained_model": True}},
    )
    irreps_node_features: str = Field(
        default="64x0e+32x1o+16x1e+8x2o+24x2e+8x3o+4x3e+4x4e",
        json_schema_extra={"x-disabled-when": {"use_pretrained_model": True}},
    )
    num_layers: int = Field(
        default=3,
        json_schema_extra={"x-disabled-when": {"use_pretrained_model": True}},
    )

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
        description="Energy cutoff (in Ry) for two-center integrals in LCAO.",
    )

    adv: _HamGNNInputAdvT = Field(
        default_factory=_HamGNNInputAdvT,
        json_schema_extra={"group": "advanced", "x-disabled-when": {"use_pretrained_model": True}},
    )

    @model_validator(mode='after')
    def apply_pretrained_defaults(self) -> 'HamGNNInputT':
        if not self.use_pretrained_model:
            return self
        defaults = HAMGNN_PRETRAINED_CONFIGS.get(self.model_name)
        if defaults is None:
            return self
        for key, value in defaults.items():
            if key == "adv":
                self.adv = _HamGNNInputAdvT(**value)
            else:
                setattr(self, key, value)
        return self


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
        Literal['001', '010', '011', '100', '101', '110', '111'] | None
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
        default=4,
        ge=1,
    )
    bussi_taut: float = Field(
        default=100.0,
        ge=1.0,
        description="Time constant for Bussi temperature coupling in fs",
    )
    nhc_tdamp: float = 40.0
    nhc_tchain: int = 1

class NVTInputT(BaseModel):
    """Input parameters for NVT molecular dynamics."""
    model_config = ConfigDict(json_schema_extra={
        "x-ui-note": [
            "NVT simulations can be run for multiple rounds with different thermostats and step counts per round.",
            "<b>1st round (Warmup)</b>: Recommend <code>rescale_v</code> or <code>bussi</code> thermostat with a larger step count to steadily reach equilibrium.",
            "<b>Subsequent rounds (Production)</b>: Temperature fixed at <code>temp_end</code>. Recommend <code>bussi</code> or <code>nhc</code> thermostats with fewer steps for correct ensemble sampling.",
            "Convergence check is enabled in production rounds. NVT completes once convergence is reached or the round count is exhausted.",
        ]
    })

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

    software: Literal['vasp', 'nequip', 'mace'] = 'vasp'

    calculator: DFTBaseInputT | NequipInputT | MACEInputT = Field(
        default_factory=DFTBaseInputT,
        json_schema_extra={
            "discriminator": {
                "propertyName": "software",
                "mapping": {
                    "vasp": "#/$defs/DFTBaseInputT",
                    "nequip": "#/$defs/NequipInputT",
                    "mace": "#/$defs/MACEInputT",
                },
            }
        },
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

    software: Literal['vasp', 'nequip', 'mace'] = 'vasp'

    calculator: DFTBaseInputT | NequipInputT | MACEInputT = Field(
        default_factory=DFTBaseInputT,
        json_schema_extra={
            "discriminator": {
                "propertyName": "software",
                "mapping": {
                    "vasp": "#/$defs/DFTBaseInputT",
                    "nequip": "#/$defs/NequipInputT",
                    "mace": "#/$defs/MACEInputT",
                },
            }
        },
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

    is_alle: bool = Field(
        False,
        description="Whether to use all-electron VASP",
        json_schema_extra={"x-show-when": {"software": "vasp"}},
    )
    
    software: Literal['vasp', 'openmx', 'hamgnn'] = 'vasp'

    calculator: DFTBaseInputT | HamGNNInputT = Field(
        default_factory=DFTBaseInputT,
        json_schema_extra={
            "discriminator": {
                "propertyName": "software",
                "mapping": {
                    "vasp": "#/$defs/DFTBaseInputT",
                    "openmx": "#/$defs/DFTBaseInputT",
                    "hamgnn": "#/$defs/HamGNNInputT",
                },
                "x-defaultOverrides": {
                    "openmx": {"scf_thr": 1e-8},
                },
            }
        },
    )


class InputT(BaseModel):
    """Input parameters for QDYN workflow."""

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
