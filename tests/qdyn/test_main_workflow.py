from types import MethodType, SimpleNamespace
from pathlib import Path

import pytest

from qdyn.input import BasicInputT, InputT, SchedulerConfigT
from qdyn.main_workflow import MainWorkflow, ConfigError


def _make_manager() -> MainWorkflow:
    """Create a MainWorkflow instance with pool-based config, bypassing __init__."""
    manager = MainWorkflow.__new__(MainWorkflow)
    manager.config = {
        "worker_pools": {
            "local_slurm": {
                "worker": {
                    "partition": "chu",
                    "cpus_per_node": 96,
                    "nvt": {"vasp": {"nodes": 1, "ntasks_per_node": 96, "cpus_per_task": 1}},
                },
                "pool": {
                    "size": 3,
                    "max_jobs": 1,
                    "work_dir_base": "/tmp/runs",
                    "resources": {"partition": "chu"},
                },
            },
        },
        "active_pool": "local_slurm",
    }
    manager.jf_config = {
        "workers": {
            "local_slurm_001": {"type": "local", "resources": {"partition": "chu"}},
            "local_slurm_002": {"type": "local", "resources": {"partition": "chu"}},
            "local_slurm_003": {"type": "local", "resources": {"partition": "chu"}},
        }
    }
    manager.active_pool_name = "local_slurm"
    pool_def = manager.config["worker_pools"]["local_slurm"]
    manager.pool_worker_cfg = pool_def["worker"]
    manager.pool_config = pool_def["pool"]
    manager.task_ids = []
    manager.job_ids = {}
    manager.jc = None
    manager._ensure_job_controller = MethodType(lambda self: None, manager)
    return manager


def test_is_remote_worker_recognizes_local():
    manager = _make_manager()
    assert manager._is_remote_worker("local_slurm_001") is False


def test_resolve_pool_context():
    manager = _make_manager()
    name, worker_cfg, pool_cfg = manager._resolve_pool_context()
    assert name == "local_slurm"
    assert worker_cfg["partition"] == "chu"
    assert pool_cfg["size"] == 3


def test_get_pool_workers():
    manager = _make_manager()
    workers = manager._get_pool_workers("local_slurm")
    assert workers == ["local_slurm_001", "local_slurm_002", "local_slurm_003"]


def test_submit_uses_pool_dispatch(monkeypatch):
    manager = _make_manager()
    captured: dict[str, object] = {}

    def fake_main_workflow(self, **kwargs):
        captured["worker_name"] = kwargs["worker_name"]
        captured["worker_cfg"] = kwargs["worker_cfg"]
        captured["runtime_worker"] = kwargs["runtime_worker"]
        return {"nvt": [SimpleNamespace(uuid="job-1")]}

    class DummyFlow:
        def __init__(self, jobs, **kwargs):
            captured["jobs"] = jobs
            self.uuid = kwargs["uuid"]

        def update_metadata(self, metadata, dynamic=False):
            pass

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

    task_id, job_ids, effective_worker = manager.submit(
        payload,
        pool_name="local_slurm",
        runtime_worker="local_slurm_002",
        username="testuser",
        task_id="task-1",
    )

    assert task_id == "task-1"
    assert job_ids == {"nvt": ["job-1"]}
    assert effective_worker == "local_slurm_002"
    assert captured["worker_name"] == "local_slurm"
    assert captured["runtime_worker"] == "local_slurm_002"
    assert captured["submitted_worker"] == "local_slurm_002"


def test_load_config_requires_worker_pools(tmp_path: Path):
    jf_config = tmp_path / "jf.yaml"
    jf_config.write_text("workers: {}\n", encoding="utf-8")

    qdyn_config = tmp_path / "qdyn.yaml"
    qdyn_config.write_text(
        f"basic:\n  jf_project_path: {jf_config.as_posix()}\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="Missing 'worker_pools'"):
        MainWorkflow._load_config(str(qdyn_config))
