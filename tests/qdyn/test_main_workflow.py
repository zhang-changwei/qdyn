from types import MethodType, SimpleNamespace

from qdyn.input import BasicInputT, InputT, SchedulerConfigT
from qdyn.main_workflow import MainWorkflow


def _make_manager() -> MainWorkflow:
    manager = MainWorkflow.__new__(MainWorkflow)
    manager.config = {
        "workers": {
            "local_slurm": {"nvt": {"vasp": {"nodes": 1}}},
            "remote_gpu": {"nvt": {"vasp": {"nodes": 2}}},
        }
    }
    manager.jf_config = {
        "workers": {
            "local_slurm": {"type": "local", "resources": {}},
            "remote_gpu": {"type": "separated_transfer", "resources": {}},
        }
    }
    manager.worker_name = "local_slurm"
    manager.worker_cfg = manager.config["workers"]["local_slurm"]
    manager.task_ids = []
    manager.job_ids = {}
    manager.jc = None
    manager._ensure_job_controller = MethodType(lambda self: None, manager)
    return manager


def test_is_remote_worker_recognizes_separated_transfer():
    manager = _make_manager()

    assert manager._is_remote_worker("remote_gpu") is True
    assert manager._is_remote_worker("local_slurm") is False


def test_submit_uses_requested_worker_without_mutating_instance(monkeypatch):
    manager = _make_manager()
    captured: dict[str, object] = {}

    def fake_main_workflow(self, **kwargs):
        captured["worker_name"] = kwargs["worker_name"]
        captured["worker_cfg"] = kwargs["worker_cfg"]
        return {"nvt": [SimpleNamespace(uuid="job-1")]}

    class DummyFlow:
        def __init__(self, jobs):
            captured["jobs"] = jobs
            self.uuid = "task-1"

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

    task_id, job_ids, effective_worker = manager.submit(payload, worker="remote_gpu")

    assert task_id == "task-1"
    assert job_ids == {"nvt": ["job-1"]}
    assert effective_worker == "remote_gpu"
    assert captured["worker_name"] == "remote_gpu"
    assert captured["worker_cfg"] == manager.config["workers"]["remote_gpu"]
    assert captured["submitted_worker"] == "remote_gpu"
    assert manager.worker_name == "local_slurm"
    assert manager.worker_cfg == manager.config["workers"]["local_slurm"]
