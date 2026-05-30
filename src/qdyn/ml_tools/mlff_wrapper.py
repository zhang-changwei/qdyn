# Note: Do not import any torch related modules at the top level of this file.
# Instead, import torch inside the functions that require it.

from pathlib import Path
from ase.calculators.calculator import Calculator
from ase.calculators.mixing import SumCalculator
import ase.units

from ..input import NequipInputT, MACEInputT, HamGNNInputT, DispersionInputT
from ..params import MACE_PRETRAINED_MODEL_URLS
from ..pool import WorkerPool

def nequip_pretrained_model_filename(model_name: str, device: str) -> str:
    return f"{model_name.replace('/', '__')}_{device}__0.1.nequip.pt2"

def mace_pretrained_model_filename(model_name: str) -> str:
    return Path(MACE_PRETRAINED_MODEL_URLS[model_name]).name

def hamgnn_pretrained_model_filename(model_name: str) -> str:
    return f"{model_name}.ckpt"


def resolve_model_path(pool: WorkerPool, calc: NequipInputT | MACEInputT | HamGNNInputT) -> str:
    """Return the worker-visible model path for ML-based NVE calculators."""
    if isinstance(calc, NequipInputT):
        if calc.use_pretrained_model:
            assert calc.model_name
            device = 'cuda' if calc.use_gpu else 'cpu'
            model_name = nequip_pretrained_model_filename(calc.model_name, device)
            return f"~/.qdyn/pretrained/{model_name}"
        return pool.get_user_file_path("model", calc.model_hash)

    if isinstance(calc, MACEInputT):
        if calc.use_pretrained_model:
            assert calc.model_name
            model_name = mace_pretrained_model_filename(calc.model_name)
            return f"~/.qdyn/pretrained/{model_name}"
        return pool.get_user_file_path("model", calc.model_hash)
    
    if isinstance(calc, HamGNNInputT):
        if calc.use_pretrained_model:
            assert calc.model_name
            model_name = hamgnn_pretrained_model_filename(calc.model_name)
            return f"~/.qdyn/pretrained/{model_name}"
        return pool.get_user_file_path("model", calc.model_hash)

    return ""


convert_energy = {'eV': ase.units.eV,
                  'Ry': ase.units.Ry,
                  'Ha': ase.units.Ha}
convert_length = {'Ang': ase.units.Angstrom,
                  'Bohr': ase.units.Bohr}

def get_mlff_calculator(
    calc: NequipInputT | MACEInputT, 
    model_path: str,
    *,
    dispersion: DispersionInputT | None = None,
) -> Calculator | SumCalculator:
    """Return the initialized MLFF calculator for the given input and model path."""
    import torch

    model_path_ = Path(model_path).expanduser().resolve()
    if not model_path_.is_file():
        raise FileNotFoundError(f"Model file not found at {model_path_}")
    
    device = 'cuda' if calc.use_gpu else 'cpu'
    dtype = torch.float32

    if isinstance(calc, NequipInputT):
        try:
            from nequip.integrations.ase import NequIPCalculator
        except ImportError:
            raise ImportError("NequIP is not installed or is too old."
                              "Please update the package and try again.")
        
        calculator = NequIPCalculator.from_compiled_model(
            compile_path=model_path_,
            device=device,
            energy_unit=convert_energy[calc.energy_unit],
            length_unit=convert_length[calc.length_unit],
        )

    elif isinstance(calc, MACEInputT):
        from mace.calculators import MACECalculator

        dtype = calc.default_dtype
        calculator = MACECalculator(
            model_paths=str(model_path_),
            device=device,
            default_dtype=dtype,
        )
    else:
        raise NotImplementedError()
    
    
    if dispersion:
        try:
            from torch_dftd.torch_dftd3_calculator import TorchDFTD3Calculator
        except ImportError as exc:
            raise RuntimeError(
                "Please install torch-dftd to use dispersion corrections "
                "(see https://github.com/pfnet-research/torch-dftd)"
            ) from exc
        
        vdw_method = dispersion.algo
        damping = dispersion.damping
        dispersion_xc = dispersion.xc
        dispersion_cutoff = dispersion.cutoff
        old = (vdw_method == "dftd2")
        if not dispersion_cutoff:
            dispersion_cutoff = 56.6918 if old else 90.0
        dispersion_cutoff *= ase.units.Bohr
        if dtype == 'float32':
            dtype = torch.float32
        elif dtype == 'float64':
            dtype = torch.float64

        d3_calc = TorchDFTD3Calculator(
            device=device,
            damping=damping,
            old=old,
            dtype=dtype,
            xc=dispersion_xc,
            cutoff=dispersion_cutoff,
        )

        return SumCalculator([calculator, d3_calc])
    
    return calculator
