import logging

import pytest

from qdyn.validation import ConfigError, validate_and_fill_runtime_config


def _make_runtime_config() -> dict:
    return {
        "basic": {
            "jf_project_path": "C:/tmp/jf.yaml",
            "jf_project_name": "jf_qdyn",
        },
        "worker_pools": {
            "local_slurm": {
                "pool": {
                    "work_dir_base": "/tmp/qdyn",
                },
                "worker": {
                    "partition": "queue1",
                    "cpus_per_node": 64,
                    "nvt": {
                        "vasp": {
                            "nodes": 1,
                            "ntasks_per_node": 64,
                            "cpus_per_task": 1,
                        }
                    },
                    "nve": {
                        "vasp": {
                            "nodes": 1,
                            "ntasks_per_node": 64,
                            "cpus_per_task": 1,
                        }
                    },
                    "scf": {
                        "vasp": {
                            "nodes": 1,
                            "ntasks_per_node": 64,
                            "cpus_per_task": 1,
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
            active_pool_name="local_slurm",
        )

    assert config["active_pool"] == "local_slurm"
    assert config["basic"]["user_db_path"] == "data/qdyn_users.db"
    assert config["basic"]["user_data"] == "data/user_data"
    assert config["basic"]["mongo_dir"] == "mongo/"
    assert config["basic"]["port"] == 8000
    assert config["auth"]["secret_key"] == ""
    assert config["auth"]["token_expire_hours"] == 24
    assert config["worker_pools"]["local_slurm"]["pool"]["queue_poll_interval"] == 60
    assert config["worker_pools"]["local_slurm"]["worker"]["type"] == "local"
    assert config["worker_pools"]["local_slurm"]["worker"]["resources"] == {}
    assert config["worker_pools"]["local_slurm"]["worker"]["orb_path"] == {}

    warning_text = caplog.text
    assert "basic.user_db_path" in warning_text
    assert "auth.token_expire_hours" in warning_text
    assert "active_pool" in warning_text
    assert "worker_pools.local_slurm.pool.queue_poll_interval" in warning_text


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
            active_pool_name="local_slurm",
        )


def test_validate_and_fill_runtime_config_requires_jf_project_name():
    config = _make_runtime_config()
    del config["basic"]["jf_project_name"]

    with pytest.raises(ConfigError, match="Missing 'basic.jf_project_name'"):
        validate_and_fill_runtime_config(
            config,
            _make_jf_config(),
            active_pool_name="local_slurm",
        )


def test_validate_and_fill_runtime_config_requires_jf_workers():
    config = _make_runtime_config()

    with pytest.raises(
        ConfigError,
        match="Missing 'workers' in jobflow-remote project config",
    ):
        validate_and_fill_runtime_config(
            config,
            {},
            active_pool_name="local_slurm",
        )
