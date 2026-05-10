from pathlib import Path
from ase.calculators.calculator import Calculator
from ase.calculators.mixing import SumCalculator
import ase.units

from ..input import NequipInputT, MACEInputT
from ..params import MACE_PRETRAINED_MODEL_URLS
from ..pool import WorkerPool

def nequip_pretrained_model_filename(model_name: str, device: str) -> str:
    return f"{model_name.replace('/', '__')}_{device}__0.1.nequip.pt2"

def mace_pretrained_model_filename(model_name: str) -> str:
    return Path(MACE_PRETRAINED_MODEL_URLS[model_name]).name


def resolve_model_path(pool: WorkerPool, calc: NequipInputT | MACEInputT) -> str:
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
    dispersion: bool = False,
    damping: str = "bj",  # choices: ["zero", "bj", "zerom", "bjm"]
    dispersion_xc: str = "pbe",
    dispersion_cutoff: float = 40.0 * ase.units.Bohr,
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
            from nequip.ase.nequip_calculator import NequIPCalculator
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
        from mace.calculators import MACECalculator, mace_mp

        dtype = calc.default_dtype
        calculator = MACECalculator(
            model_paths=str(model_path_),
            device=device,
            default_dtype=dtype,
        )
        # TODO: dispersion correction for MACE
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

        d3_calc = TorchDFTD3Calculator(
            device=device,
            damping=damping,
            dtype=dtype,
            xc=dispersion_xc,
            cutoff=dispersion_cutoff,
        )

        return SumCalculator([calculator, d3_calc])
    
    return calculator
