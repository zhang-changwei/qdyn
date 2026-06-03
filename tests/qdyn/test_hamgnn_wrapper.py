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
            or name == "torch"
            or name.startswith("torch_geometric")
            or name.startswith("pytorch_lightning")
        ):
            sys.modules.pop(name, None)

    torch_module = ModuleType("torch")
    torch_module.Tensor = type("Tensor", (), {})
    torch_module.float32 = object()
    torch_module.long = object()
    torch_module.set_num_threads = lambda threads: None
    torch_module.set_num_interop_threads = lambda threads: None
    monkeypatch.setitem(sys.modules, "torch", torch_module)

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

    hamgnn_output = ModuleType("hamgnn.models.hamgnn_output")
    class DummyHamGNNPlusPlusOut:
        def _initialize_openmx_basis(self, *args, **kwargs):
            self.basis_def = {}
    hamgnn_output.HamGNNPlusPlusOut = DummyHamGNNPlusPlusOut

    hamgnn_models = ModuleType("hamgnn.models")
    hamgnn_models.__path__ = []

    monkeypatch.setitem(
        sys.modules,
        "hamgnn",
        ModuleType("hamgnn"),
    )
    monkeypatch.setitem(sys.modules, "hamgnn.main", hamgnn_main)
    monkeypatch.setitem(sys.modules, "hamgnn.config", ModuleType("hamgnn.config"))
    monkeypatch.setitem(sys.modules, "hamgnn.config.config_parsing", hamgnn_cfg)
    monkeypatch.setitem(sys.modules, "hamgnn.models", hamgnn_models)
    monkeypatch.setitem(sys.modules, "hamgnn.models.Model", hamgnn_model)
    monkeypatch.setitem(sys.modules, "hamgnn.models.hamgnn_output", hamgnn_output)

    module = importlib.import_module("qdyn.ml_tools.hamgnn_wrapper")
    return module


def test_mlscfsolver_uses_spawn_and_preserves_input_batch_size(
    monkeypatch, tmp_path: Path, hamgnn_wrapper_module
):
    MLSCFSolver = hamgnn_wrapper_module.MLSCFSolver

    model_path = tmp_path / "model.ckpt"
    model_path.write_text("stub", encoding="utf-8")

    class DummyPool:
        def close(self):
            pass

        def join(self):
            pass

    class DummyManager:
        def Queue(self):
            return Queue()

        def shutdown(self):
            pass

    class DummyCtx:
        def __init__(self):
            self.pool_kwargs = None

        def Manager(self):
            return DummyManager()

        def Pool(self, **kwargs):
            self.pool_kwargs = kwargs
            return DummyPool()

    context_calls = []
    dummy_ctx = DummyCtx()
    monkeypatch.setattr(
        "qdyn.ml_tools.hamgnn_wrapper.multiprocessing.get_context",
        lambda method: context_calls.append(method) or dummy_ctx,
    )

    mlh_input = _make_hamgnn_input(batch_size=5)
    solver = MLSCFSolver(
        software="openmx",
        mlh_input=mlh_input,
        model_path=str(model_path),
        logger=SimpleNamespace(),
        nproc=2,
        threads_per_proc=3,
    )
    solver.close()

    assert context_calls == ["spawn"]
    assert mlh_input.batch_size == 5
    assert solver.predict_batch_size == 2
    assert solver.batch_size == 4
    assert dummy_ctx.pool_kwargs["processes"] == 2
    assert dummy_ctx.pool_kwargs["initializer"] is hamgnn_wrapper_module.init_spawn_worker
    assert dummy_ctx.pool_kwargs["initargs"][0] == "openmx"
    assert dummy_ctx.pool_kwargs["initargs"][1] is not mlh_input
    assert dummy_ctx.pool_kwargs["initargs"][1].batch_size == 5
    assert dummy_ctx.pool_kwargs["initargs"][3] == 3
    assert dummy_ctx.pool_kwargs["initargs"][4] == 2


def test_init_spawn_worker_populates_orbital_basis(
    monkeypatch, tmp_path: Path, hamgnn_wrapper_module
):
    model_path = tmp_path / "model.ckpt"
    model_path.write_text("stub", encoding="utf-8")

    monkeypatch.setattr(
        "qdyn.ml_tools.hamgnn_wrapper.HamGNNWrapper",
        lambda config, model_path, device="cpu": SimpleNamespace(nao_max=config.nao_max),
    )
    hamgnn_wrapper_module.ORBITAL_BASIS.clear()

    mlh_input = _make_hamgnn_input(batch_size=4)
    hamgnn_wrapper_module.init_spawn_worker(
        software="openmx",
        mlh_input=mlh_input,
        model_path=str(model_path),
        threads_per_proc=1,
        predict_batch_size=2,
        eigen_dtype=hamgnn_wrapper_module.np.float32,
    )

    assert hamgnn_wrapper_module.ORBITAL_BASIS
    assert "S" in hamgnn_wrapper_module.ORBITAL_BASIS


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
            steps = args[0]
            task_dirs = args[2]
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
            self._manager = SimpleNamespace(
                queue=Queue(),
                shutdown_called=False,
            )

        def Manager(self):
            def make_queue():
                return self._manager.queue

            def shutdown():
                self._manager.shutdown_called = True

            return SimpleNamespace(Queue=make_queue, shutdown=shutdown)

        def Pool(self, processes, initializer=None, initargs=()):
            return self._pool

        def Queue(self):
            return Queue()

    logger_calls = []

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
    first_steps = dummy_pool.calls[0][1][0]
    second_steps = dummy_pool.calls[1][1][0]
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
