import io
import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Collection

import ase.io
import yaml

from .errors import ConfigError, ValidationError, ResumeError
from .input import InputT
from .pool import WorkerPool
from .resources import normalize_worker_resources, validate_step_resources

SUPPORTED_SOFTWARE = ["vasp", "vasp_ae", "abacus", "python", "namd"]
SOFTWARE_MAPPING = {
    "vasp_ae": "vasp",
    "vasp": "vasp",
    "abacus": "abacus",
    "python": "python",
    "namd": "namd",
}


def _expand_steps_for_validation(steps: Collection[str]) -> list[str]:
    expanded: list[str] = []
    has_fused = "fused_scf_prenamd" in steps
    if has_fused and ("scf" in steps or "pre_namd" in steps):
        raise ValidationError(
            "Step 'fused_scf_prenamd' cannot be used together with 'scf' or 'pre_namd'."
        )

    for step in steps:
        if step == "fused_scf_prenamd":
            expanded.extend(["scf", "pre_namd"])
        else:
            expanded.append(step)
    return expanded

def _require_mapping(node: Any, err_msg: str) -> dict[str, Any]:
    """Ensure the node is a mapping and return it."""
    if not isinstance(node, dict):
        raise ConfigError(err_msg)
    return node


def _require_mapping_child(
    node: dict[str, Any],
    key: str,
    err_msg: str,
) -> dict[str, Any]:
    """Ensure the child node at key is a mapping and return it."""
    if key not in node:
        raise ConfigError(err_msg)
    return _require_mapping(node[key], err_msg)


def _require_present_leaf(
    node: dict[str, Any],
    key: str,
    key_type: type,
    err_msg: str,
) -> Any:
    """Ensure the leaf node at key is of type key_type, then return its value."""
    if key not in node:
        raise ConfigError(err_msg)

    value = node[key]
    if not isinstance(value, key_type):
        raise ConfigError(err_msg)
    return value


def _warn_and_fill_default_leaf(
    node: dict[str, Any],
    dotted_name: str,
    key: str,
    default: Any,
    *,
    silent: bool = False,
) -> None:
    """If key is missing in node, log a warning and fill it with the default value."""
    if key not in node:
        if not silent:
            logging.warning(
                "QDYN Config key '%s' is missing; using default value %r.",
                dotted_name,
                default,
            )
        node[key] = default
    elif not isinstance(node[key], type(default)):
        raise ConfigError(
            f"Invalid type for QDYN config key '{dotted_name}'.\n"
            f"Expected {type(default).__name__}, got {type(node[key]).__name__}."
        )


def _compute_file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def load_config(
    config_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    # The config file is readout from app.state / QDYN_CONFIG / default in lifespan.
    if not Path(config_path).is_file():
        raise ConfigError(
            f"QDYN config file not found: {config_path}\n"
            "Create config/qdyn.yaml or set the QDYN_CONFIG environment variable."
        )

    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict):
        raise ConfigError(f"Config file {config_path} is empty or invalid.")
    logging.info(f"Loaded config from {config_path}.")

    # jobflow-remote config
    try:
        jf_path = cfg["basic"]["jf_project_path"]
        jf_path = Path(jf_path).expanduser().resolve()
    except Exception as exc:
        raise ConfigError(
            "Failed to resolve jobflow-remote project path from QDYN config\n"
            "Set it by adding 'basic.jf_project_path' to QDYN config.\n"
        ) from exc
    
    if not Path(jf_path).is_file():
        raise ConfigError(
            f"Jobflow-remote project config not found: {jf_path}\n"
            "Set basic.jf_project_path in qdyn.yaml to a valid path."
        )

    with open(jf_path) as f:
        jf_cfg = yaml.safe_load(f)
    if not isinstance(jf_cfg, dict):
        raise ConfigError(f"Jobflow-remote project config at {jf_path} is empty or invalid.")
    logging.info(f"Found jobflow-remote project config at {jf_path}.")

    expected_hash = cfg.get("basic", {}).get("jf_config_hash")
    if not isinstance(expected_hash, str) or not expected_hash:
        raise ConfigError(
            "Missing 'basic.jf_config_hash' in QDYN config.\n"
            "Run scripts/generate_jf_config.py to generate jf-remote config "
            "and write the matching hash back to qdyn.yaml."
        )

    actual_hash = _compute_file_sha256(jf_path)
    if expected_hash != actual_hash:
        raise ConfigError(
            "jobflow-remote config hash mismatch.\n"
            f"Expected: {expected_hash}\n"
            f"Actual:   {actual_hash}\n"
            "Re-run scripts/generate_jf_config.py and do not edit jf_remote_cfg manually."
        )

    return cfg, jf_cfg


def validate_and_fill_runtime_config(
    cfg: dict[str, Any],
    jf_cfg: dict[str, Any],
) -> None:
    """Normalize optional keys, then validate workflow runtime requirements."""
    def _validate_installed_section(
            worker_cfg: dict[str, Any], 
            dotted_prefix: str
        ) -> list[str]:
        installed_cfg = _require_mapping_child(
            worker_cfg,
            "installed",
            err_msg=f"Missing '{dotted_prefix}.installed' section in QDYN config."
        )

        installed_software = []
        for software, installed in installed_cfg.items():
            if software not in SUPPORTED_SOFTWARE:
                raise ConfigError(
                    f"Unsupported software '{software}' in '{dotted_prefix}.installed' "
                    f"section of QDYN config.\n"
                    f"Supported software: {SUPPORTED_SOFTWARE}"
                )
            if not isinstance(installed, bool):
                raise ConfigError(
                    f"Invalid value for '{dotted_prefix}.installed.{software}' in QDYN config.\n"
                    "Should be a boolean (true/false)."
                )
            if installed:
                installed_software.append(software)

        return installed_software

    def _validate_worker_keys(
            worker_cfg: dict[str, Any],
            key: str, 
            software: str, 
            default: Any, 
            dotted_prefix: str,
            required: bool = False
        ) -> None:
        key_cfg = _require_mapping_child(
            worker_cfg,
            key,
            f"Missing '{dotted_prefix}.{key}' section in QDYN config.",
        )
        if key in ["nvt", "nve", "scf"] and software in ["vasp", "abacus"]:
            if software not in key_cfg:
                raise ConfigError(
                    f"Invalid resource config for '{dotted_prefix}.{key}.{software}' in QDYN config.\n"
                    "Should contain 'nodes', 'processes_per_node', and "
                    "'threads_per_process' as positive integers."
                )
            validate_step_resources(key_cfg[software], f"{dotted_prefix}.{key}.{software}")
            return
            
        if required:
            _require_present_leaf(
                key_cfg, 
                software, 
                type(default), 
                err_msg=f"Missing '{dotted_prefix}.{key}.{software}' in QDYN config."
            )
        else:
            _warn_and_fill_default_leaf(key_cfg, "", software, default, silent=True)        


    # basic
    basic_cfg = _require_mapping_child(cfg, "basic", err_msg="Missing 'basic' section in QDYN config.")

    _warn_and_fill_default_leaf(basic_cfg, "basic.user_db_path", "user_db_path", "data/qdyn_users.db")
    _warn_and_fill_default_leaf(basic_cfg, "basic.mongo_dir", "mongo_dir", "mongo/")
    _warn_and_fill_default_leaf(basic_cfg, "basic.port", "port", 8000)
    if "jf_project_path" not in basic_cfg or not basic_cfg["jf_project_path"]:
        raise ConfigError(
            "Missing 'basic.jf_project_path' in QDYN config.\n"
            "Set it to a valid jobflow-remote project config path."
        )
    if "jf_project_name" not in basic_cfg or not basic_cfg["jf_project_name"]:
        raise ConfigError(
            "Missing 'basic.jf_project_name' in QDYN config.\n"
            "Set it to the project name defined in your jobflow-remote config."
        )

    # auth
    auth_cfg = _require_mapping_child(cfg, "auth", err_msg="Missing 'auth' section in QDYN config.")

    _warn_and_fill_default_leaf(auth_cfg, "auth.token_expire_hours", "token_expire_hours", 24)
    if "secret_key" not in auth_cfg:
        raise ConfigError(
            "Missing 'auth.secret_key' in QDYN config.\n"
            "Set it to an empty string for auto-generated key.\n"
            "See 'config/qdyn.yaml.example' for more instructions."
        )

    # worker_pools
    worker_pools = _require_mapping_child(
        cfg, 
        "worker_pools", 
        err_msg="Missing 'worker_pools' section in QDYN config."
    )

    if len(worker_pools) == 0:
        raise ConfigError(
            "At least one worker pool must be defined "
            "in 'worker_pools' section of QDYN config."
    )

    # active_pool
    _warn_and_fill_default_leaf(cfg, "active_pool", "active_pool", next(iter(worker_pools)))
    if cfg["active_pool"] not in worker_pools:
        raise ConfigError(
            f"active_pool '{cfg['active_pool']}' not found "
            "in worker_pools section of QDYN config.\n"
            f"Available: {list(worker_pools.keys())}"
        )

    # worker_pools
    for pool_name, pool_def in worker_pools.items():
        pool_def = _require_mapping(
            pool_def, 
            err_msg=f"worker_pools.{pool_name} should be a mapping in QDYN config."
        )
        worker_cfg = _require_mapping_child(
            pool_def, 
            "worker", 
            err_msg=f"Missing 'worker_pools.{pool_name}.worker' section in QDYN config."
        )
        pool_cfg = _require_mapping_child(
            pool_def, 
            "pool", 
            err_msg=f"Missing 'worker_pools.{pool_name}.pool' section in QDYN config."
        )

        # pool
        _warn_and_fill_default_leaf(
            pool_cfg,
            f"worker_pools.{pool_name}.pool.queue_poll_interval",
            "queue_poll_interval",
            60,
        )
        _require_present_leaf(
            pool_cfg,
            "work_dir_base",
            str,
            err_msg=f"Invalid 'worker_pools.{pool_name}.pool.work_dir_base' in QDYN config. "
                    "Should be type (str)",
        )
        _require_present_leaf(
            pool_cfg,
            "size",
            int,
            err_msg=f"Invalid 'worker_pools.{pool_name}.pool.size' in QDYN config. "
                    "Should be type (int)\n"
                    "Recommend: size = nodes - max_jobs",
        )
        _require_present_leaf(
            pool_cfg,
            "user_data",
            str,
            err_msg=f"Invalid 'worker_pools.{pool_name}.pool.user_data' in QDYN config. "
                    "Should be type (str)",
        )

        # worker
        _require_present_leaf(
            worker_cfg,
            "type",
            str,
            err_msg=f"Invalid worker_pools.{pool_name}.worker.type in QDYN config. "
                     "Should be 'local' or 'remote'",
        )
        _require_present_leaf(
            worker_cfg,
            "scheduler_type",
            str,
            err_msg=f"Invalid worker_pools.{pool_name}.worker.scheduler_type in QDYN config. "
                     "Should be a valid scheduler name. E.g. 'slurm', 'pbs'",
        )
        _warn_and_fill_default_leaf(
            worker_cfg,
            f"worker_pools.{pool_name}.worker.resources",
            "resources",
            {},
        )
        worker_cfg["resources"] = normalize_worker_resources(worker_cfg["resources"])
        _require_present_leaf(
            worker_cfg,
            "cpus_per_node",
            int,
            err_msg=f"Invalid worker_pools.{pool_name}.worker.cpus_per_node in QDYN config. "
                    "Should be type (int)",
        )

        # worker.installed
        installed = _validate_installed_section(worker_cfg, f"worker_pools.{pool_name}.worker")
        installed_set = set([SOFTWARE_MAPPING[s] for s in installed])

        for software in installed_set:
            dotted_prefix = f"worker_pools.{pool_name}.worker"

            _validate_worker_keys(worker_cfg, "modules", software, [], dotted_prefix)
            _validate_worker_keys(worker_cfg, "export", software, {}, dotted_prefix)
            _validate_worker_keys(worker_cfg, "pre_run", software, "", dotted_prefix)
            pp_required = True if software in ["vasp", "abacus"] else False
            _validate_worker_keys(worker_cfg, "pp_path", software, "", dotted_prefix, pp_required)
            orb_required = True if software in ["abacus"] else False
            _validate_worker_keys(worker_cfg, "orb_path", software, "", dotted_prefix, orb_required)
            _validate_worker_keys(worker_cfg, "nvt", software, {}, dotted_prefix)
            _validate_worker_keys(worker_cfg, "nve", software, {}, dotted_prefix)
            _validate_worker_keys(worker_cfg, "scf", software, {}, dotted_prefix)


    # jf workers
    workers = _require_mapping_child(
        jf_cfg,
        "workers",
        err_msg="Missing 'workers' in jf-remote project config.")
    for worker_name, worker_cfg in workers.items():
        _require_present_leaf(
            worker_cfg, 
            "work_dir", 
            str,
            err_msg=f"Invalid 'workers.{worker_name}.worker' in jf-remote config. "
                    "Should be type (str).",
        )


def validate_workflow_input(
    input: InputT,
    method: str,
    stru: str,
    stru_format: str,
    stru_hash: str,
    resume: bool,
    prev_task_id: str,
    *,
    known_task_ids: Collection[str],
    config: dict[str, Any],
    worker_cfg: dict[str, Any],
    active_pool: WorkerPool,
) -> None:
    """Validate user workflow input before building the jobflow graph."""
    software = input.basic_input.software
    if not (software == "vasp" and method == "namd"):
        raise NotImplementedError(
            "Currently only the combination of software='vasp' and method='namd' is supported.\n"
            f"Got software='{software}', method='{method}'."
        )
    installed_cfg = worker_cfg["installed"]
    installed = [key for key, enabled in installed_cfg.items() if enabled]
    if software not in [SOFTWARE_MAPPING[s] for s in installed]:
        raise ValidationError(
            f"Software '{software}' is not installed on the worker."
        )
    required_inputs = {
        "nvt": ("nvt_input",),
        "nve": ("nve_input",),
        "scf": ("scf_input",),
        "pre_namd": ("prenamd_input",),
        "namd": ("namd_input",),
        "fused_scf_prenamd": ("scf_input", "prenamd_input"),
    }
    for step in input.steps:
        for field_name in required_inputs.get(step, ()):
            if getattr(input, field_name) is None:
                raise ValidationError(
                    f"Step '{step}' requires '{field_name}' to be provided."
                )

    # vasp_ae specific
    if (
        software == "vasp"
        and ("scf" in input.steps or "fused_scf_prenamd" in input.steps)
        and input.scf_input is not None
        and input.scf_input.is_alle
    ):

        if "vasp_ae" not in installed:
            raise ValidationError(
                "VASP_AE is required for SCF step with all-electron settings, "
                "but 'vasp_ae' is not installed on the worker."
            )

    if not input.steps:
        raise ValidationError("input.steps is empty; at least one step is required.")

    valid_steps = {"nvt", "nve", "scf", "pre_namd", "namd", "fused_scf_prenamd"}
    unknown = set(input.steps) - valid_steps  # type: ignore[arg-type]
    if unknown:
        raise ValidationError(
            f"Unknown step(s): {unknown}. Valid steps: {sorted(valid_steps)}"
        )

    if method == "namd":
        key_map = {"nvt": 0, "nve": 1, "scf": 2, "pre_namd": 3, "namd": 4}
        expanded_steps = _expand_steps_for_validation(input.steps)
        step_int = sorted(key_map[s] for s in expanded_steps)
        for i in range(1, len(step_int)):
            if step_int[i] != step_int[i - 1] + 1:
                raise ValidationError(f"Steps must be contiguous. Got: {input.steps}")
    else:
        raise NotImplementedError(f"Method '{method}' is not supported yet.")

    if resume:
        if not prev_task_id:
            raise ValidationError("prev_task_id must be provided when resume=True.")
        if prev_task_id not in known_task_ids:
            raise ResumeError(f"Previous task '{prev_task_id}' not found.")

    if stru:
        try:
            ase.io.read(io.StringIO(stru), format=stru_format, index=":")
        except Exception as exc:
            raise ValidationError(
                f"Provided structure string could not be parsed "
                f"by ASE with format '{stru_format}'."
            ) from exc

    if stru_hash:
        if not active_pool.user_file_exists("trajectory", stru_hash):
            raise ValidationError(
                f"Structure with hash '{stru_hash}' not found in the active pool."
            )
        
        from .calc_common import read_trajectory_summary
        parsed, summary = read_trajectory_summary(
            pool=active_pool,
            file_hash=stru_hash,
            formats=[stru_format],
        )
        if not parsed:
            raise ValidationError(
                f"Structure with hash '{stru_hash}' could not be parsed "
                f"by ASE with format '{stru_format}'."
            )
