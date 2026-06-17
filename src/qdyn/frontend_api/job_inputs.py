"""Input parameter display services backed by jfremote_in.json."""

import json
from typing import Any

from ..main_workflow import MainWorkflow
from ._common import _detect_step_type, _get_task_run_dir_access
from .run_dir_access import RunDirAccess
from .models import JobInputParamsResponse


_PARAMETERS_TITLE_BY_STEP = {
    "nvt": "NVT Parameters",
    "nve": "NVE Parameters",
    "scf": "SCF Parameters",
    "fused_scf_prenamd": "FUSED_SCF_PRENAMD Parameters",
    "fused_cat": "FUSED_CAT Parameters",
    "pre_namd": "PRE_NAMD Parameters",
    "namd": "NAMD Parameters",
}


def get_job_input_params(
    manager: MainWorkflow, task_id: str, job_uuid: str
) -> JobInputParamsResponse:
    """Read job input parameters from a job's run directory."""
    access = _get_task_run_dir_access(manager, task_id, job_uuid)
    if access is None:
        return JobInputParamsResponse(available=False)

    job_info = manager.get_job_info(job_uuid)
    step_type = _detect_step_type(job_info.name, access.run_dir_path)

    parameters = _read_job_parameters(access)
    if parameters is None:
        return JobInputParamsResponse(
            available=False,
            warning="Failed to load job parameters from jfremote_in.json.",
        )
    return JobInputParamsResponse(
        available=True,
        parameters=parameters,
        parameters_title=_get_parameters_title(step_type),
    )


def _get_parameters_title(step_type: str) -> str:
    """Return the frontend title for serialized job parameters."""
    return _PARAMETERS_TITLE_BY_STEP.get(step_type, "Job Parameters")


def _read_job_parameters(
    access: RunDirAccess,
) -> dict[str, str] | None:
    """Read serialized job parameters from ``jfremote_in.json``."""
    try:
        raw_text = access.read_root_text("jfremote_in.json")
    except Exception:
        return None

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return None

    function_kwargs = payload.get("job", {}).get("function_kwargs", {})
    if not isinstance(function_kwargs, dict) or not function_kwargs:
        return None

    flattened = _flatten_parameter_mapping(function_kwargs)
    return flattened or None


_SKIP_TOPLEVEL_KEYS = {"structure"}

_MAX_DISPLAY_LENGTH = 200


def _flatten_parameter_mapping(
    value: dict[str, Any], prefix: str = ""
) -> dict[str, str]:
    """Flatten nested parameter dicts into display-friendly key/value pairs."""
    flattened: dict[str, str] = {}
    for key, item in value.items():
        if str(key).startswith("@"):
            continue
        current_key = f"{prefix}.{key}" if prefix else str(key)
        toplevel = current_key.split(".")[0]
        if toplevel in _SKIP_TOPLEVEL_KEYS:
            continue
        if isinstance(item, dict):
            flattened.update(_flatten_parameter_mapping(item, current_key))
            continue
        text = _stringify_parameter_value(item)
        if len(text) > _MAX_DISPLAY_LENGTH:
            continue
        flattened[current_key] = text
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
