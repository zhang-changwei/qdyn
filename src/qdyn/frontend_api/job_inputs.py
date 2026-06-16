"""Input parameter display services (INCAR, KPOINTS, jfremote_in.json)."""

import json
import logging
from pathlib import Path
from typing import Any, Dict

from ..main_workflow import MainWorkflow
from ._common import _detect_step_type, _get_task_run_dir_access
from .run_dir_access import RunDirAccess
from .models import JobInputParamsResponse

logger = logging.getLogger(__name__)


_PARAMETERS_TITLE_BY_STEP = {
    "nvt": "NVT Parameters",
    "nve": "NVE Parameters",
    "scf": "SCF Parameters",
    "fused_scf_prenamd": "FUSED_SCF_PRENAMD Parameters",
    "fused_cat": "FUSED_CAT Parameters",
    "pre_namd": "PRE_NAMD Parameters",
    "namd": "NAMD Parameters",
}


def _parse_incar_file(incar_path: Path) -> Dict[str, str]:
    """Parse an INCAR file into a key-value dictionary."""
    try:
        from pymatgen.io.vasp import Incar

        incar = Incar.from_file(str(incar_path))
        return {str(k): str(v) for k, v in incar.items()}
    except Exception as exc:
        logger.warning("Failed to parse INCAR at %s: %s", incar_path, exc)
        return {}


def _parse_incar_text(text: str) -> Dict[str, str]:
    """Parse INCAR text content into a key-value dictionary.

    Uses pymatgen's ``Incar.from_string()`` for robust handling.
    Falls back to simple line-based parsing if pymatgen is unavailable.
    """
    try:
        from pymatgen.io.vasp import Incar

        incar = Incar.from_string(text)
        return {str(k): str(v) for k, v in incar.items()}
    except Exception:
        result: Dict[str, str] = {}
        for line in text.splitlines():
            line = line.split("!")[0].split("#")[0].strip()
            if "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                if key:
                    result[key] = val
        return result


def get_job_input_params(
    manager: MainWorkflow, task_id: str, job_uuid: str
) -> JobInputParamsResponse:
    """Read job input parameters from a job's run directory."""
    access = _get_task_run_dir_access(manager, task_id, job_uuid)
    if access is None:
        return JobInputParamsResponse(available=False)

    job_info = manager.get_job_info(job_uuid)
    step_type = _detect_step_type(job_info.name, access.run_dir_path)

    parameters = _read_non_vasp_job_parameters(access)
    if parameters is not None:
        return JobInputParamsResponse(
            available=True,
            parameters=parameters,
            parameters_title=_get_parameters_title(step_type),
        )

    incar: Dict[str, str] | None = None
    kpoints_text: str | None = None
    warnings: list[str] = []

    try:
        texts = access.read_multiple_root_texts(["INCAR", "KPOINTS"])
    except Exception as exc:
        warnings.append(f"Failed to read input files: {exc}")
        texts = {}

    if "INCAR" in texts:
        try:
            incar = _parse_incar_text(texts["INCAR"])
        except Exception as exc:
            warnings.append(f"Failed to parse INCAR: {exc}")
    else:
        warnings.append("INCAR not found")

    if "KPOINTS" in texts:
        kpoints_text = texts["KPOINTS"]
    else:
        warnings.append("KPOINTS not found")

    if incar is None and kpoints_text is None:
        warnings = ["Failed to load job parameters from jfremote_in.json."]

    warning_str = "; ".join(warnings) if warnings else None

    return JobInputParamsResponse(
        available=True,
        incar=incar,
        kpoints_text=kpoints_text,
        warning=warning_str,
    )


def _get_parameters_title(step_type: str) -> str:
    """Return the frontend title for serialized job parameters."""
    return _PARAMETERS_TITLE_BY_STEP.get(step_type, "Job Parameters")


def _read_non_vasp_job_parameters(
    access: RunDirAccess,
) -> Dict[str, str] | None:
    """Read serialized non-VASP job parameters from ``jfremote_in.json``."""
    try:
        raw_text = access.read_root_text("jfremote_in.json")
    except Exception:
        return None

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return None

    parameters = (
        payload.get("job", {})
        .get("function_kwargs", {})
        .get("parameters")
    )
    if not isinstance(parameters, dict):
        return None

    flattened = _flatten_parameter_mapping(parameters)
    return flattened or None


def _flatten_parameter_mapping(
    value: dict[str, Any], prefix: str = ""
) -> Dict[str, str]:
    """Flatten nested parameter dicts into display-friendly key/value pairs."""
    flattened: Dict[str, str] = {}
    for key, item in value.items():
        if str(key).startswith("@"):
            continue
        current_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, dict):
            flattened.update(_flatten_parameter_mapping(item, current_key))
            continue
        flattened[current_key] = _stringify_parameter_value(item)
    return flattened


def _stringify_parameter_value(value: Any) -> str:
    """Convert a parameter value to a compact string for UI display."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)
