from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from qtoolkit.core.data_objects import QResources

from .errors import ConfigError


STEP_RESOURCE_KEYS = ("nodes", "processes_per_node", "threads_per_process")
RESOURCE_ALIASES = {
    "ntasks_per_node": "processes_per_node",
    "cpus_per_task": "threads_per_process",
}


def normalize_worker_resources(resources: Mapping[str, Any]) -> dict[str, Any]:
    """Keep portable execution fields top-level and pass scheduler fields through."""
    if not isinstance(resources, Mapping):
        raise ConfigError("worker.resources should be a mapping in QDYN config.")

    normalized: dict[str, Any] = {}
    scheduler_kwargs: dict[str, Any] = {}

    for key, value in resources.items():
        if key == "scheduler_kwargs":
            if value is None:
                continue
            if not isinstance(value, Mapping):
                raise ConfigError("worker.resources.scheduler_kwargs should be a mapping.")
            scheduler_kwargs.update(value)
            continue

        normalized_key = RESOURCE_ALIASES.get(key, key)
        if normalized_key in STEP_RESOURCE_KEYS:
            normalized[normalized_key] = value
        else:
            scheduler_kwargs[key] = value

    if scheduler_kwargs:
        normalized["scheduler_kwargs"] = scheduler_kwargs
    return normalized


def validate_step_resources(resources: Any, dotted_name: str) -> None:
    """Validate per-step resources, which must use portable QDYN names."""
    if not isinstance(resources, dict):
        raise ConfigError(
            f"Invalid resource config for '{dotted_name}' in QDYN config.\n"
            "Should be a mapping with 'nodes', 'processes_per_node', and "
            "'threads_per_process'."
        )

    missing_keys = [key for key in STEP_RESOURCE_KEYS if key not in resources]
    if missing_keys:
        raise ConfigError(
            f"Invalid resource config for '{dotted_name}' in QDYN config.\n"
            "Missing required field(s): "
            f"{missing_keys}. Required fields are {list(STEP_RESOURCE_KEYS)}."
        )

    for key in STEP_RESOURCE_KEYS:
        value = resources[key]
        if not isinstance(value, int) or value <= 0:
            raise ConfigError(
                f"Invalid resource config for '{dotted_name}' in QDYN config.\n"
                f"Field '{key}' should be a positive integer."
            )


def build_qresources(
    worker_cfg: Mapping[str, Any],
    step_resources: Mapping[str, Any] | None = None,
    use_gpu: bool = False,
    **overrides: Any,
) -> QResources:
    """
    Merge worker, step, and explicit overrides into QResources.

    Notice:
    if use_gpu, step_resources and overrides are ignored, 
    We only support single GPU card jobs.
    """
    if use_gpu:
        resources = normalize_worker_resources(worker_cfg['gpu_resources'])
    else:
        resources = normalize_worker_resources(worker_cfg['resources'])
        if step_resources is not None:
            resources.update(step_resources)
        resources.update(
            {
                key: value
                for key, value in overrides.items()
                if value is not None
            }
        )

    try:
        return QResources(**resources)
    except Exception as exc:
        raise ConfigError(
            "Invalid QDYN resource configuration after QResources normalization."
        ) from exc
