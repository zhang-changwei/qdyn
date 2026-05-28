from __future__ import annotations

import importlib
import sys
from pathlib import Path
from queue import Queue
from types import ModuleType, SimpleNamespace

import pytest


def _make_hamgnn_input(batch_size: int = 4):
    return SimpleNamespace(
        batch_size=batch_size,
        add_H0=False,
        nao_max=13,
        adv=SimpleNamespace(eigen_dtype="float32"),
    )


@pytest.fixture
def hamgnn_wrapper_module(monkeypatch):
    for name in list(sys.modules):
        if (
            name == "qdyn.ml_tools.hamgnn_wrapper"
            or name.startswith("hamgnn")
            or name.startswith("pymatgen")
            or name.startswith("scipy")
            or name.startswith("torch_geometric")
            or name.startswith("pytorch_lightning")
        ):
            sys.modules.pop(name, None)

    pymatgen_core = ModuleType("pymatgen.core")
    pymatgen_core.Element = SimpleNamespace(
        from_Z=lambda z: SimpleNamespace(symbol="H")
    )
    monkeypatch.setitem(sys.modules, "pymatgen", ModuleType("pymatgen"))
    monkeypatch.setitem(sys.modules, "pymatgen.core", pymatgen_core)

    tg_data = ModuleType("torch_geometric.data")
    tg_data.Dataset = object
    tg_data.Data = object
    tg_loader = ModuleType("torch_geometric.loader")
    tg_loader.DataLoader = list
    monkeypatch.setitem(sys.modules, "torch_geometric", ModuleType("torch_geometric"))
    monkeypatch.setitem(sys.modules, "torch_geometric.data", tg_data)
    monkeypatch.setitem(sys.modules, "torch_geometric.loader", tg_loader)

    pl_module = ModuleType("pytorch_lightning")
    pl_module.seed_everything = lambda seed: None
    monkeypatch.setitem(sys.modules, "pytorch_lightning", pl_module)

    scipy_module = ModuleType("scipy")
    scipy_linalg = ModuleType("scipy.linalg")
    scipy_linalg.eigh = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "scipy", scipy_module)
    monkeypatch.setitem(sys.modules, "scipy.linalg", scipy_linalg)

    hamgnn_main = ModuleType("hamgnn.main")
    hamgnn_main.build_hamgnn_model = lambda config: (None, None, None)
    hamgnn_cfg = ModuleType("hamgnn.config.config_parsing")
    hamgnn_cfg.config_default = {
        "output_nets": {"HamGNN_out": {}},
        "representation_nets": {"HamGNN_pre": {}},
    }
    hamgnn_model = ModuleType("hamgnn.models.Model")
    hamgnn_model.Model = SimpleNamespace(
        load_from_checkpoint=lambda **kwargs: None
    )

    monkeypatch.setitem(
        sys.modules,
        "hamgnn",
        ModuleType("hamgnn"),
    )
    monkeypatch.setitem(sys.modules, "hamgnn.main", hamgnn_main)
    monkeypatch.setitem(sys.modules, "hamgnn.config", ModuleType("hamgnn.config"))
    monkeypatch.setitem(sys.modules, "hamgnn.config.config_parsing", hamgnn_cfg)
    monkeypatch.setitem(sys.modules, "hamgnn.models", ModuleType("hamgnn.models"))
    monkeypatch.setitem(sys.modules, "hamgnn.models.Model", hamgnn_model)

    module = importlib.import_module("qdyn.ml_tools.hamgnn_wrapper")
    return module


def test_mlscfsolver_rejects_non_linux(monkeypatch, tmp_path: Path, hamgnn_wrapper_module):
    MLSCFSolver = hamgnn_wrapper_module.MLSCFSolver

    model_path = tmp_path / "model.ckpt"
    model_path.write_text("stub", encoding="utf-8")

    monkeypatch.setattr("qdyn.ml_tools.hamgnn_wrapper.sys.platform", "win32")

    with pytest.raises(RuntimeError, match="only supports Linux/fork"):
        MLSCFSolver(
            software="openmx",
            mlh_input=_make_hamgnn_input(),
            model_path=str(model_path),
            logger=SimpleNamespace(),
        )


def test_mlscfsolver_run_chunks_tasks_and_logs_progress(
    monkeypatch, tmp_path: Path, hamgnn_wrapper_module
):
    from ase import Atoms
    MLSCFSolver = hamgnn_wrapper_module.MLSCFSolver

    model_path = tmp_path / "model.ckpt"
    model_path.write_text("stub", encoding="utf-8")

    class DummyResult:
        def __init__(self):
            self._ready = True

        def ready(self):
            return self._ready

        def get(self):
            return None

    class DummyPool:
        def __init__(self):
            self.calls = []
            self.closed = False
            self.joined = False
            self.terminated = False

        def apply_async(self, func, args):
            self.calls.append((func, args))
            progress_queue = args[-1]
            steps = args[3]
            task_dirs = args[5]
            for step, task_dir in zip(steps, task_dirs):
                progress_queue.put(
                    {"type": "prehamgnn", "step": step, "task_dir": task_dir}
                )
                progress_queue.put(
                    {"type": "posthamgnn", "step": step, "task_dir": task_dir}
                )
            return DummyResult()

        def close(self):
            self.closed = True

        def join(self):
            self.joined = True

        def terminate(self):
            self.terminated = True

    class DummyCtx:
        def __init__(self, pool):
            self._pool = pool

        def Pool(self, processes, initializer=None, initargs=()):
            if initializer is not None:
                initializer(*initargs)
            return self._pool

        def Queue(self):
            return Queue()

    logger_calls = []

    monkeypatch.setattr("qdyn.ml_tools.hamgnn_wrapper.sys.platform", "linux")
    monkeypatch.setattr(
        "qdyn.ml_tools.hamgnn_wrapper.HamGNNWrapper",
        lambda config, model_path, device="cpu": SimpleNamespace(nao_max=config.nao_max),
    )

    dummy_pool = DummyPool()
    monkeypatch.setattr(
        "qdyn.ml_tools.hamgnn_wrapper.multiprocessing.get_context",
        lambda method: DummyCtx(dummy_pool),
    )

    solver = MLSCFSolver(
        software="openmx",
        mlh_input=_make_hamgnn_input(batch_size=4),
        model_path=str(model_path),
        logger=lambda step, global_idx, category: logger_calls.append(
            (step, global_idx, category)
        ),
        nproc=2,
        threads_per_proc=1,
    )

    stru = Atoms("H", positions=[[0.0, 0.0, 0.0]])
    solver.tasks = [
        (0, tmp_path / "scf_0001", stru),
        (1, tmp_path / "scf_0002", stru),
        (2, tmp_path / "scf_0003", stru),
        (3, tmp_path / "scf_0004", stru),
    ]
    solver.task_count = 4

    solver.run()

    assert len(dummy_pool.calls) == 2
    first_steps = dummy_pool.calls[0][1][3]
    second_steps = dummy_pool.calls[1][1][3]
    assert first_steps == [0, 2]
    assert second_steps == [1, 3]
    assert logger_calls == [
        (0, "scf_0001", "prehamgnn"),
        (0, "scf_0001", "posthamgnn"),
        (2, "scf_0003", "prehamgnn"),
        (2, "scf_0003", "posthamgnn"),
        (1, "scf_0002", "prehamgnn"),
        (1, "scf_0002", "posthamgnn"),
        (3, "scf_0004", "prehamgnn"),
        (3, "scf_0004", "posthamgnn"),
    ]
