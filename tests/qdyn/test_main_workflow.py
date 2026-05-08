import hashlib
from pathlib import Path
from types import MethodType, SimpleNamespace

import pytest
from qtoolkit import QResources

from qdyn.errors import QueryError, ValidationError
from qdyn.input import BasicInputT, InputT, SCFInputT, SchedulerConfigT
from qdyn.main_workflow import ConfigError, MainWorkflow
from qdyn.resources import build_qresources
from qdyn.validation import (
    load_config,
    validate_and_fill_runtime_config,
    validate_workflow_input,
)


def _make_manager() -> MainWorkflow:
    manager = MainWorkflow.__new__(MainWorkflow)
    manager.config = {
        "worker_pools": {
            "local_slurm": {
                "worker": {
                    "type": "local",
                    "scheduler_type": "slurm",
                    "partition": "chu",
                    "cpus_per_node": 96,
                    "resources": {"partition": "chu"},
                    "gpu_resources": None,
                    "installed": {
                        "vasp": True,
                        "vasp_ae": False,
                        "abacus": False,
                        "python": True,
                        "namd": True,
                    },
                    "modules": {"vasp": [], "python": [], "namd": []},
                    "export": {"vasp": {}, "python": {}, "namd": {}},
                    "pre_run": {"vasp": "", "python": "", "namd": ""},
                    "pp_path": {"vasp": "/pp"},
                    "orb_path": {"vasp": "/orb"},
                    "nvt": {"vasp": {"nodes": 1, "processes_per_node": 96, "threads_per_process": 1}},
                    "nve": {"vasp": {"nodes": 1, "processes_per_node": 96, "threads_per_process": 1}},
                    "scf": {"vasp": {"nodes": 1, "processes_per_node": 4, "threads_per_process": 2}},
                },
                "pool": {
                    "size": 3,
                    "max_jobs": 1,
                    "work_dir_base": "/tmp/runs",
                    "user_data": "/tmp/user_data",
                    "queue_poll_interval": 60,
                },
            },
            "remote_pool": {
                "worker": {
                    "type": "remote",
                    "scheduler_type": "slurm",
                    "partition": "gpu",
                    "cpus_per_node": 64,
                    "resources": {"partition": "gpu"},
                    "gpu_resources": None,
                    "installed": {
                        "vasp": True,
                        "vasp_ae": False,
                        "abacus": False,
                        "python": True,
                        "namd": True,
                    },
                    "modules": {"vasp": [], "python": [], "namd": []},
                    "export": {"vasp": {}, "python": {}, "namd": {}},
                    "pre_run": {"vasp": "", "python": "", "namd": ""},
                    "pp_path": {"vasp": "/remote/pp"},
                    "orb_path": {"vasp": "/remote/orb"},
                    "nvt": {"vasp": {"nodes": 1, "processes_per_node": 64, "threads_per_process": 1}},
                    "nve": {"vasp": {"nodes": 1, "processes_per_node": 64, "threads_per_process": 1}},
                    "scf": {"vasp": {"nodes": 1, "processes_per_node": 8, "threads_per_process": 2}},
                },
                "pool": {
                    "size": 2,
                    "max_jobs": 1,
                    "work_dir_base": "/remote/runs",
                    "user_data": "/remote/user_data",
                    "queue_poll_interval": 60,
                },
            },
        },
        "active_pool": "local_slurm",
    }
    manager.jf_config = {
        "workers": {
            "local_slurm_001": {
                "type": "local",
                "resources": {"partition": "chu"},
                "work_dir": "/tmp/runs/001",
            },
            "local_slurm_002": {
                "type": "local",
                "resources": {"partition": "chu"},
                "work_dir": "/tmp/runs/002",
            },
            "local_slurm_003": {
                "type": "local",
                "resources": {"partition": "chu"},
                "work_dir": "/tmp/runs/003",
            },
            "remote_pool_001": {
                "type": "remote",
                "resources": {"partition": "gpu"},
                "work_dir": "/remote/runs/001",
                "host": "remote.example.com",
            },
        }
    }
    manager.task_ids = []
    manager.job_ids = {}
    manager.jc = None
    manager._pool_cache = {}
    manager._ensure_job_controller = MethodType(
        lambda self: SimpleNamespace(project=object(), jobs=SimpleNamespace(aggregate=lambda pipeline: [])),
        manager,
    )
    manager.init_active_pool()
    return manager


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_get_pool_returns_active_pool_instance():
    manager = _make_manager()

    assert manager.get_pool("local_slurm") is manager.active_pool


def test_get_pool_workers_uses_workerpool():
    manager = _make_manager()

    assert manager.active_pool.get_pool_workers() == [
        "local_slurm_001",
        "local_slurm_002",
        "local_slurm_003",
    ]


def test_get_task_pool_name_prefers_task_metadata(monkeypatch):
    manager = _make_manager()

    monkeypatch.setattr(
        "qdyn.database.qdyndb.get_task_metadata",
        lambda task_id: {"pool_name": "remote_pool"} if task_id == "task-1" else None,
    )
    monkeypatch.setattr(
        "qdyn.database.qdyndb.get_queued_status",
        lambda task_id: None,
    )

    assert manager.get_task_pool_name("task-1") == "remote_pool"


def test_get_task_pool_name_falls_back_to_queue(monkeypatch):
    manager = _make_manager()

    monkeypatch.setattr("qdyn.database.qdyndb.get_task_metadata", lambda task_id: None)
    monkeypatch.setattr(
        "qdyn.database.qdyndb.get_queued_status",
        lambda task_id: {"pool_name": "remote_pool"} if task_id == "task-1" else None,
    )

    assert manager.get_task_pool_name("task-1") == "remote_pool"


def test_get_task_pool_name_raises_when_missing(monkeypatch):
    manager = _make_manager()

    monkeypatch.setattr("qdyn.database.qdyndb.get_task_metadata", lambda task_id: None)
    monkeypatch.setattr("qdyn.database.qdyndb.get_queued_status", lambda task_id: None)

    with pytest.raises(QueryError, match="Pool for task 'task-1' not found"):
        manager.get_task_pool_name("task-1")


def test_build_qresources_uses_qresources_with_override_order():
    resources = build_qresources(
        {
            "partition": "base",
            "nodes": 9,
            "ntasks_per_node": 9,
            "cpus_per_task": 9,
        },
        {"nodes": 2, "processes_per_node": 4, "threads_per_process": 8},
        nodes=3,
    )

    assert isinstance(resources, QResources)
    assert resources.queue_name is None
    assert resources.nodes == 3
    assert resources.processes_per_node == 4
    assert resources.threads_per_process == 8
    assert resources.scheduler_kwargs == {"partition": "base"}


def test_submit_uses_active_pool_context(monkeypatch):
    manager = _make_manager()
    captured: dict[str, object] = {}

    def fake_main_workflow(self, **kwargs):
        return {"nvt": [SimpleNamespace(uuid="job-1")]}

    class DummyFlow:
        def __init__(self, jobs, **kwargs):
            captured["jobs"] = jobs
            captured["metadata"] = kwargs["metadata"]
            self.uuid = kwargs["uuid"]

        def update_metadata(self, metadata, dynamic=False):
            captured["updated_metadata"] = metadata

    monkeypatch.setattr("qdyn.main_workflow.Flow", DummyFlow)
    monkeypatch.setattr(
        "qdyn.main_workflow.submit_flow",
        lambda flow, worker: captured.setdefault("submitted_worker", worker),
    )
    manager.main_workflow = MethodType(fake_main_workflow, manager)

    payload = InputT(
        basic_input=BasicInputT(),
        scheduler_config=SchedulerConfigT(),
        steps=["nvt"],
    )

    task_id, job_ids, active_worker = manager.submit(
        payload,
        pool_name="local_slurm",
        runtime_worker="local_slurm_002",
        username="testuser",
        task_id="task-1",
    )

    assert task_id == "task-1"
    assert job_ids == {"nvt": ["job-1"]}
    assert active_worker == "local_slurm_002"
    assert captured["submitted_worker"] == "local_slurm_002"
    assert captured["metadata"]["qdyn_pool"] == "local_slurm"
    assert captured["metadata"]["qdyn_runtime_worker"] == "local_slurm_002"


def test_submit_rejects_non_active_pool(monkeypatch):
    manager = _make_manager()

    monkeypatch.setattr(
        "qdyn.main_workflow.submit_flow",
        lambda flow, worker: None,
    )
    manager.main_workflow = MethodType(
        lambda self, **kwargs: {"nvt": [SimpleNamespace(uuid="job-1")]},
        manager,
    )

    payload = InputT(
        basic_input=BasicInputT(),
        scheduler_config=SchedulerConfigT(),
        steps=["nvt"],
    )

    with pytest.raises(ValidationError, match="restricted to the active pool 'local_slurm'"):
        manager.submit(payload, pool_name="remote_pool", task_id="task-1")


def test_switch_active_pool_not_implemented():
    manager = _make_manager()

    with pytest.raises(NotImplementedError, match="Switching active pool is not implemented yet"):
        manager.switch_active_pool("remote_pool")


def test_load_config_requires_worker_pools(tmp_path: Path):
    jf_config = tmp_path / "jf.yaml"
    jf_config.write_text("workers: {}\n", encoding="utf-8")
    jf_hash = _file_sha256(jf_config)

    qdyn_config = tmp_path / "qdyn.yaml"
    qdyn_config.write_text(
        (
            "basic:\n"
            f"  jf_project_path: {jf_config.as_posix()}\n"
            "  jf_project_name: jf_qdyn\n"
            f"  jf_config_hash: '{jf_hash}'\n"
            "auth:\n"
            "  secret_key: ''\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="Missing 'worker_pools'"):
        cfg, jf_cfg = load_config(qdyn_config)
        validate_and_fill_runtime_config(cfg, jf_cfg)


def test_load_config_requires_jf_config_hash(tmp_path: Path):
    jf_config = tmp_path / "jf.yaml"
    jf_config.write_text("workers: {}\n", encoding="utf-8")

    qdyn_config = tmp_path / "qdyn.yaml"
    qdyn_config.write_text(
        (
            "basic:\n"
            f"  jf_project_path: {jf_config.as_posix()}\n"
            "  jf_project_name: jf_qdyn\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="Missing 'basic.jf_config_hash'"):
        load_config(qdyn_config)


def test_load_config_rejects_mismatched_jf_config_hash(tmp_path: Path):
    jf_config = tmp_path / "jf.yaml"
    jf_config.write_text("workers: {}\n", encoding="utf-8")

    qdyn_config = tmp_path / "qdyn.yaml"
    qdyn_config.write_text(
        (
            "basic:\n"
            f"  jf_project_path: {jf_config.as_posix()}\n"
            "  jf_project_name: jf_qdyn\n"
            "  jf_config_hash: 'not-the-real-hash'\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="jobflow-remote config hash mismatch"):
        load_config(qdyn_config)


def test_validate_workflow_input_requires_fused_inputs(tmp_path: Path):
    payload = InputT(
        basic_input=BasicInputT(),
        scheduler_config=SchedulerConfigT(),
        scf_input=SCFInputT(),
        steps=["fused_scf_prenamd"],
    )
    worker_cfg = {
        "installed": {
            "vasp": True,
            "vasp_ae": False,
            "abacus": False,
            "python": True,
            "namd": True,
        }
    }
    config = {
        "active_pool": "local_slurm",
        "worker_pools": {
            "local_slurm": {
                "pool": {"user_data": str(tmp_path)},
                "worker": {"type": "local"},
            }
        },
    }

    active_pool = SimpleNamespace(user_file_exists=lambda *_: False)

    with pytest.raises(
        ValidationError,
        match="Step 'fused_scf_prenamd' requires 'prenamd_input'",
    ):
        validate_workflow_input(
            payload,
            method="namd",
            stru="",
            stru_format="vasp",
            stru_hash="",
            resume=False,
            prev_task_id="",
            known_task_ids=[],
            config=config,
            worker_cfg=worker_cfg,
            active_pool=active_pool,
        )


def test_validate_workflow_input_rejects_hash_when_stru_format_mismatches(monkeypatch):
    payload = InputT(
        basic_input=BasicInputT(),
        scheduler_config=SchedulerConfigT(),
        scf_input=SCFInputT(),
        steps=["scf"],
    )
    worker_cfg = {
        "installed": {
            "vasp": True,
            "vasp_ae": False,
            "abacus": False,
            "python": True,
            "namd": True,
        }
    }
    config = {
        "active_pool": "local_slurm",
        "worker_pools": {
            "local_slurm": {
                "pool": {"user_data": "/tmp/user_data"},
                "worker": {"type": "local"},
            }
        },
    }
    active_pool = SimpleNamespace(user_file_exists=lambda *_: True)

    def fake_read_trajectory_summary(*, pool, file_hash, formats):
        if formats == ["vasp-xdatcar"]:
            return True, {"format": "vasp-xdatcar"}
        return False, {}

    monkeypatch.setattr(
        "qdyn.calc_common.read_trajectory_summary",
        fake_read_trajectory_summary,
    )

    with pytest.raises(
        ValidationError,
        match="could not be parsed .* format 'extxyz'",
    ):
        validate_workflow_input(
            payload,
            method="namd",
            stru="",
            stru_format="extxyz",
            stru_hash="traj-hash",
            resume=False,
            prev_task_id="",
            known_task_ids=[],
            config=config,
            worker_cfg=worker_cfg,
            active_pool=active_pool,
        )


def test_step_scf_uses_active_pool_user_data_path(monkeypatch):
    manager = _make_manager()
    manager.active_pool = manager.get_pool("remote_pool")

    captured: dict[str, object] = {}

    def fake_qdyn_scf(**kwargs):
        captured["traj_path"] = kwargs["traj_path"]
        captured["traj_format"] = kwargs["traj_format"]
        return [SimpleNamespace(uuid="job-1")]

    monkeypatch.setattr("qdyn.main_workflow.qdyn_scf", fake_qdyn_scf)
    monkeypatch.setattr("qdyn.main_workflow.set_run_config", lambda job, **_: job)

    payload = InputT(
        basic_input=BasicInputT(),
        scheduler_config=SchedulerConfigT(),
        scf_input=SCFInputT(),
        steps=["scf"],
    )

    jobs = manager.step_scf(
        input=payload,
        jobs={},
        is_first_step=False,
        stru="",
        stru_format="extxyz",
        stru_hash="traj-hash",
        resume=False,
        prev_task_id="",
        prepare_input_only=False,
    )

    assert [job.uuid for job in jobs] == ["job-1"]
    assert captured["traj_path"] == "/remote/user_data/trajectory/traj-hash"
    assert captured["traj_format"] == "extxyz"


def test_workerpool_remote_property_uses_worker_type():
    manager = _make_manager()

    assert manager.get_pool("local_slurm").remote is False
    assert manager.get_pool("remote_pool").remote is True
