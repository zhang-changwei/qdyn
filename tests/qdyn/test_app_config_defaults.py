import logging

import pytest

from qdyn.resources import normalize_worker_resources
from qdyn.validation import ConfigError, validate_and_fill_runtime_config


def _make_runtime_config() -> dict:
    return {
        "basic": {
            "jf_project_path": "C:/tmp/jf.yaml",
            "jf_project_name": "jf_qdyn",
        },
        "auth": {
            "secret_key": "",
        },
        "worker_pools": {
            "local_slurm": {
                "pool": {
                    "size": 3,
                    "work_dir_base": "/tmp/qdyn",
                    "user_data": "/tmp/qdyn_user_data",
                },
                "worker": {
                    "type": "local",
                    "scheduler_type": "slurm",
                    "gpu_resources": None,
                    "cpus_per_node": 64,
                    "installed": {
                        "vasp": True,
                        "vasp_ae": False,
                        "abacus": False,
                        "python": False,
                        "namd": False,
                    },
                    "resources": {},
                    "modules": {
                        "vasp": [],
                    },
                    "export": {
                        "vasp": {},
                    },
                    "pre_run": {
                        "vasp": "",
                    },
                    "pp_path": {
                        "vasp": "/tmp/pp",
                    },
                    "orb_path": {},
                    "nvt": {
                        "vasp": {
                            "nodes": 1,
                            "processes_per_node": 64,
                            "threads_per_process": 1,
                        }
                    },
                    "nve": {
                        "vasp": {
                            "nodes": 1,
                            "processes_per_node": 64,
                            "threads_per_process": 1,
                        }
                    },
                    "scf": {
                        "vasp": {
                            "nodes": 1,
                            "processes_per_node": 64,
                            "threads_per_process": 1,
                        }
                    },
                },
            }
        },
    }


def _make_jf_config() -> dict:
    return {
        "workers": {
            "local_slurm_001": {
                "type": "local",
                "resources": {},
                "work_dir": "/tmp/qdyn/001",
            }
        }
    }


def test_validate_and_fill_runtime_config_warns_and_sets_optional_defaults(caplog):
    config = _make_runtime_config()

    with caplog.at_level(logging.WARNING):
        validate_and_fill_runtime_config(
            config,
            _make_jf_config(),
        )

    assert config["active_pool"] == "local_slurm"
    assert config["basic"]["user_db_path"] == "data/qdyn_users.db"
    assert config["basic"]["mongo_dir"] == "mongo/"
    assert config["basic"]["port"] == 8000
    assert config["auth"]["secret_key"] == ""
    assert config["auth"]["token_expire_hours"] == 24
    assert config["worker_pools"]["local_slurm"]["pool"]["queue_poll_interval"] == 60
    assert config["worker_pools"]["local_slurm"]["pool"]["user_data"] == "/tmp/qdyn_user_data"
    assert config["worker_pools"]["local_slurm"]["worker"]["type"] == "local"
    assert config["worker_pools"]["local_slurm"]["worker"]["resources"] == {}
    assert config["worker_pools"]["local_slurm"]["worker"]["gpu_resources"] is None
    assert config["worker_pools"]["local_slurm"]["worker"]["orb_path"] == {}
    assert config["worker_pools"]["local_slurm"]["worker"]["modules"]["vasp"] == []
    assert config["worker_pools"]["local_slurm"]["worker"]["export"]["vasp"] == {}
    assert config["worker_pools"]["local_slurm"]["worker"]["pre_run"]["vasp"] == ""

    warning_text = caplog.text
    assert "basic.user_db_path" in warning_text
    assert "auth.token_expire_hours" in warning_text
    assert "active_pool" in warning_text
    assert "worker_pools.local_slurm.pool.queue_poll_interval" in warning_text


def test_validate_and_fill_runtime_config_normalizes_worker_resource_aliases():
    config = _make_runtime_config()
    config["worker_pools"]["local_slurm"]["worker"]["resources"] = {
        "partition": "chu",
        "time": "48:00:00",
        "ntasks_per_node": 32,
        "cpus_per_task": 2,
    }

    validate_and_fill_runtime_config(
        config,
        _make_jf_config(),
    )

    assert config["worker_pools"]["local_slurm"]["worker"]["resources"] == {
        "processes_per_node": 32,
        "threads_per_process": 2,
        "scheduler_kwargs": {
            "partition": "chu",
            "time": "48:00:00",
        },
    }


def test_validate_and_fill_runtime_config_rejects_old_step_resource_names():
    config = _make_runtime_config()
    config["worker_pools"]["local_slurm"]["worker"]["nvt"]["vasp"] = {
        "nodes": 1,
        "ntasks_per_node": 64,
        "cpus_per_task": 1,
    }

    with pytest.raises(ConfigError, match="processes_per_node"):
        validate_and_fill_runtime_config(
            config,
            _make_jf_config(),
        )


def test_normalize_worker_resources_maps_ntasks_and_cpus_per_task():
    resources = normalize_worker_resources(
        {"nodes": 1, "ntasks_per_node": 4, "cpus_per_task": 2, "p": 2}
    )

    assert resources == {
        "nodes": 1,
        "processes_per_node": 4,
        "threads_per_process": 2,
        "scheduler_kwargs": {"p": 2},
    }


def test_validate_and_fill_runtime_config_requires_non_optional_runtime_keys():
    config = _make_runtime_config()
    del config["worker_pools"]["local_slurm"]["worker"]["nvt"]

    with pytest.raises(
        ConfigError,
        match="Missing 'worker_pools.local_slurm.worker.nvt'",
    ):
        validate_and_fill_runtime_config(
            config,
            _make_jf_config(),
        )


def test_validate_and_fill_runtime_config_requires_pool_user_data():
    config = _make_runtime_config()
    del config["worker_pools"]["local_slurm"]["pool"]["user_data"]

    with pytest.raises(
        ConfigError,
        match="worker_pools.local_slurm.pool.user_data",
    ):
        validate_and_fill_runtime_config(
            config,
            _make_jf_config(),
        )


def test_validate_and_fill_runtime_config_requires_jf_project_name():
    config = _make_runtime_config()
    del config["basic"]["jf_project_name"]

    with pytest.raises(ConfigError, match="Missing 'basic.jf_project_name'"):
        validate_and_fill_runtime_config(
            config,
            _make_jf_config(),
        )


def test_validate_and_fill_runtime_config_requires_jf_workers():
    config = _make_runtime_config()

    with pytest.raises(
        ConfigError,
        match="Missing 'workers' in jf-remote project config",
    ):
        validate_and_fill_runtime_config(
            config,
            {},
        )


def test_validate_and_fill_runtime_config_requires_gpu_resources():
    config = _make_runtime_config()
    del config["worker_pools"]["local_slurm"]["worker"]["gpu_resources"]

    with pytest.raises(
        ConfigError,
        match="Missing 'worker_pools.local_slurm.worker.gpu_resources'",
    ):
        validate_and_fill_runtime_config(
            config,
            _make_jf_config(),
        )


def test_validate_and_fill_runtime_config_accepts_mapping_gpu_resources():
    config = _make_runtime_config()
    config["worker_pools"]["local_slurm"]["worker"]["gpu_resources"] = {
        "partition": "gpu",
        "gres": "gpu:4",
    }

    validate_and_fill_runtime_config(
        config,
        _make_jf_config(),
    )

    assert config["worker_pools"]["local_slurm"]["worker"]["gpu_resources"] == {
        "partition": "gpu",
        "gres": "gpu:4",
    }


def test_validate_and_fill_runtime_config_rejects_invalid_gpu_resources_type():
    config = _make_runtime_config()
    config["worker_pools"]["local_slurm"]["worker"]["gpu_resources"] = ["gpu"]

    with pytest.raises(
        ConfigError,
        match="worker.gpu_resources",
    ):
        validate_and_fill_runtime_config(
            config,
            _make_jf_config(),
        )
