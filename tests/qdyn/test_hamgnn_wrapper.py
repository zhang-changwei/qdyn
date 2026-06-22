from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
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
            or name == "pymatgen"
            or name.startswith("pymatgen.")
            or name == "scipy"
            or name.startswith("scipy.")
            or name == "qdyn.calc_common"
            or name == "qdyn.output_postprocess"
            or name == "qdyn.input"
            or name == "qdyn.tools.run_software"
            or name == "qdyn.tools.scf"
        ):
            monkeypatch.delitem(sys.modules, name, raising=False)

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

    scipy_module = ModuleType("scipy")
    scipy_linalg = ModuleType("scipy.linalg")
    scipy_linalg.eigh = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "scipy", scipy_module)
    monkeypatch.setitem(sys.modules, "scipy.linalg", scipy_linalg)

    calc_common = ModuleType("qdyn.calc_common")

    @contextmanager
    def change_dir(path):
        yield

    calc_common.change_dir = change_dir
    calc_common.select_orbitals = lambda software, nao_max: {"S": [0]}
    monkeypatch.setitem(sys.modules, "qdyn.calc_common", calc_common)

    output_postprocess = ModuleType("qdyn.output_postprocess")
    output_postprocess.read_scfout = lambda path: {}
    output_postprocess.calc_openmx_HK_SK_gamma = lambda data, tdt=False: None
    monkeypatch.setitem(sys.modules, "qdyn.output_postprocess", output_postprocess)

    input_module = ModuleType("qdyn.input")
    input_module.HamGNNInputT = object
    monkeypatch.setitem(sys.modules, "qdyn.input", input_module)

    run_software_module = ModuleType("qdyn.tools.run_software")
    run_software_module.run_software = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "qdyn.tools.run_software", run_software_module)

    scf_module = ModuleType("qdyn.tools.scf")
    scf_module.SCFLogger = object
    monkeypatch.setitem(sys.modules, "qdyn.tools.scf", scf_module)

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

    class DummyPsutilProcess:
        def __init__(self):
            self._affinity = list(range(64))

        def cpu_affinity(self, cpus=None):
            if cpus is None:
                return list(self._affinity)
            self._affinity = list(cpus)

    psutil_module = ModuleType("psutil")
    psutil_module.Process = DummyPsutilProcess
    psutil_module.pid_exists = lambda pid: False

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
    monkeypatch.setitem(sys.modules, "psutil", psutil_module)
    element_symbols = {
        1: "H",
        6: "C",
        7: "N",
        8: "O",
        14: "Si",
    }
    element_numbers = {
        symbol: number for number, symbol in element_symbols.items()
    }

    class DummyElement:
        def __init__(self, symbol):
            self.symbol = symbol
            self.Z = element_numbers[symbol]

        @classmethod
        def from_Z(cls, number):
            return cls(element_symbols[number])

    pymatgen_module = ModuleType("pymatgen")
    pymatgen_core = ModuleType("pymatgen.core")
    pymatgen_core.Element = DummyElement
    monkeypatch.setitem(sys.modules, "pymatgen", pymatgen_module)
    monkeypatch.setitem(sys.modules, "pymatgen.core", pymatgen_core)

    module = importlib.import_module("qdyn.ml_tools.hamgnn_wrapper")
    return module


def test_mlscfsolver_uses_spawn_and_aligns_input_batch_size(
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

    assert context_calls == []
    with solver:
        pass

    assert context_calls == ["spawn"]
    assert mlh_input.batch_size == 4
    assert solver.batch_size == 4
    assert dummy_ctx.pool_kwargs["processes"] == 2
    assert dummy_ctx.pool_kwargs["initializer"] is hamgnn_wrapper_module.init_spawn_worker
    assert dummy_ctx.pool_kwargs["initargs"][0] == "openmx"
    assert dummy_ctx.pool_kwargs["initargs"][1] is not mlh_input
    assert dummy_ctx.pool_kwargs["initargs"][1].batch_size == 4
    assert dummy_ctx.pool_kwargs["initargs"][3] == 2
    assert dummy_ctx.pool_kwargs["initargs"][4] == 3
    assert dummy_ctx.pool_kwargs["initargs"][5] == 2


def test_mlscfsolver_close_is_idempotent(
    monkeypatch, tmp_path: Path, hamgnn_wrapper_module
):
    MLSCFSolver = hamgnn_wrapper_module.MLSCFSolver

    model_path = tmp_path / "model.ckpt"
    model_path.write_text("stub", encoding="utf-8")

    class DummyPool:
        def __init__(self):
            self.close_calls = 0
            self.join_calls = 0
            self.terminate_calls = 0

        def close(self):
            self.close_calls += 1

        def join(self):
            self.join_calls += 1

        def terminate(self):
            self.terminate_calls += 1

    class DummyManager:
        def __init__(self):
            self.shutdown_calls = 0

        def Queue(self):
            return Queue()

        def shutdown(self):
            self.shutdown_calls += 1

    class DummyCtx:
        def __init__(self):
            self.pool = DummyPool()
            self.manager = DummyManager()

        def Manager(self):
            return self.manager

        def Pool(self, **kwargs):
            return self.pool

    dummy_ctx = DummyCtx()
    monkeypatch.setattr(
        "qdyn.ml_tools.hamgnn_wrapper.multiprocessing.get_context",
        lambda method: dummy_ctx,
    )

    solver = MLSCFSolver(
        software="openmx",
        mlh_input=_make_hamgnn_input(batch_size=4),
        model_path=str(model_path),
        logger=SimpleNamespace(),
        nproc=2,
        threads_per_proc=1,
    )

    solver.__enter__()
    solver.close()
    solver.close()

    assert dummy_ctx.pool.close_calls == 1
    assert dummy_ctx.pool.join_calls == 1
    assert dummy_ctx.pool.terminate_calls == 0
    assert dummy_ctx.manager.shutdown_calls == 1


def test_mlscfsolver_init_failure_shuts_down_manager(
    monkeypatch, tmp_path: Path, hamgnn_wrapper_module
):
    MLSCFSolver = hamgnn_wrapper_module.MLSCFSolver

    model_path = tmp_path / "model.ckpt"
    model_path.write_text("stub", encoding="utf-8")

    class DummyManager:
        def __init__(self):
            self.shutdown_calls = 0

        def Queue(self):
            return Queue()

        def shutdown(self):
            self.shutdown_calls += 1

    class DummyCtx:
        def __init__(self):
            self.manager = DummyManager()

        def Manager(self):
            return self.manager

        def Pool(self, **kwargs):
            raise RuntimeError("pool boom")

    dummy_ctx = DummyCtx()
    monkeypatch.setattr(
        "qdyn.ml_tools.hamgnn_wrapper.multiprocessing.get_context",
        lambda method: dummy_ctx,
    )

    solver = MLSCFSolver(
        software="openmx",
        mlh_input=_make_hamgnn_input(batch_size=4),
        model_path=str(model_path),
        logger=SimpleNamespace(),
        nproc=2,
        threads_per_proc=1,
    )

    with pytest.raises(RuntimeError, match="pool boom"):
        with solver:
            pass

    assert dummy_ctx.manager.shutdown_calls == 1


def test_mlscfsolver_run_requires_context(
    tmp_path: Path, hamgnn_wrapper_module
):
    MLSCFSolver = hamgnn_wrapper_module.MLSCFSolver

    model_path = tmp_path / "model.ckpt"
    model_path.write_text("stub", encoding="utf-8")

    solver = MLSCFSolver(
        software="openmx",
        mlh_input=_make_hamgnn_input(batch_size=4),
        model_path=str(model_path),
        logger=SimpleNamespace(),
        nproc=2,
        threads_per_proc=1,
    )
    solver.task_count = 1

    with pytest.raises(RuntimeError, match="must be used as a context manager"):
        solver.run()


def test_mlscfsolver_context_exit_closes_pool(
    monkeypatch, tmp_path: Path, hamgnn_wrapper_module
):
    MLSCFSolver = hamgnn_wrapper_module.MLSCFSolver

    model_path = tmp_path / "model.ckpt"
    model_path.write_text("stub", encoding="utf-8")

    class DummyPool:
        def __init__(self):
            self.close_calls = 0
            self.join_calls = 0
            self.terminate_calls = 0

        def close(self):
            self.close_calls += 1

        def join(self):
            self.join_calls += 1

        def terminate(self):
            self.terminate_calls += 1

    class DummyManager:
        def __init__(self):
            self.shutdown_calls = 0

        def Queue(self):
            return Queue()

        def shutdown(self):
            self.shutdown_calls += 1

    class DummyCtx:
        def __init__(self):
            self.pool = DummyPool()
            self.manager = DummyManager()

        def Manager(self):
            return self.manager

        def Pool(self, **kwargs):
            return self.pool

    dummy_ctx = DummyCtx()
    monkeypatch.setattr(
        "qdyn.ml_tools.hamgnn_wrapper.multiprocessing.get_context",
        lambda method: dummy_ctx,
    )

    with MLSCFSolver(
        software="openmx",
        mlh_input=_make_hamgnn_input(batch_size=4),
        model_path=str(model_path),
        logger=SimpleNamespace(),
        nproc=2,
        threads_per_proc=1,
    ):
        pass

    assert dummy_ctx.pool.close_calls == 1
    assert dummy_ctx.pool.join_calls == 1
    assert dummy_ctx.pool.terminate_calls == 0
    assert dummy_ctx.manager.shutdown_calls == 1


def test_mlscfsolver_context_exit_terminates_pool_on_error(
    monkeypatch, tmp_path: Path, hamgnn_wrapper_module
):
    MLSCFSolver = hamgnn_wrapper_module.MLSCFSolver

    model_path = tmp_path / "model.ckpt"
    model_path.write_text("stub", encoding="utf-8")

    class DummyPool:
        def __init__(self):
            self.close_calls = 0
            self.join_calls = 0
            self.terminate_calls = 0

        def close(self):
            self.close_calls += 1

        def join(self):
            self.join_calls += 1

        def terminate(self):
            self.terminate_calls += 1

    class DummyManager:
        def __init__(self):
            self.shutdown_calls = 0

        def Queue(self):
            return Queue()

        def shutdown(self):
            self.shutdown_calls += 1

    class DummyCtx:
        def __init__(self):
            self.pool = DummyPool()
            self.manager = DummyManager()

        def Manager(self):
            return self.manager

        def Pool(self, **kwargs):
            return self.pool

    dummy_ctx = DummyCtx()
    monkeypatch.setattr(
        "qdyn.ml_tools.hamgnn_wrapper.multiprocessing.get_context",
        lambda method: dummy_ctx,
    )

    with pytest.raises(ValueError, match="context boom"):
        with MLSCFSolver(
            software="openmx",
            mlh_input=_make_hamgnn_input(batch_size=4),
            model_path=str(model_path),
            logger=SimpleNamespace(),
            nproc=2,
            threads_per_proc=1,
        ):
            raise ValueError("context boom")

    assert dummy_ctx.manager.shutdown_calls == 1
    assert dummy_ctx.pool.terminate_calls == 1
    assert dummy_ctx.pool.join_calls == 1
    assert dummy_ctx.pool.close_calls == 0


def test_mlscfsolver_context_exit_raises_cleanup_error_on_error(
    monkeypatch, tmp_path: Path, hamgnn_wrapper_module
):
    MLSCFSolver = hamgnn_wrapper_module.MLSCFSolver

    model_path = tmp_path / "model.ckpt"
    model_path.write_text("stub", encoding="utf-8")

    class DummyPool:
        def __init__(self):
            self.join_calls = 0
            self.terminate_calls = 0

        def join(self):
            self.join_calls += 1

        def terminate(self):
            self.terminate_calls += 1
            raise RuntimeError("terminate boom")

    class DummyManager:
        def __init__(self):
            self.shutdown_calls = 0

        def Queue(self):
            return Queue()

        def shutdown(self):
            self.shutdown_calls += 1

    class DummyCtx:
        def __init__(self):
            self.pool = DummyPool()
            self.manager = DummyManager()

        def Manager(self):
            return self.manager

        def Pool(self, **kwargs):
            return self.pool

    dummy_ctx = DummyCtx()
    monkeypatch.setattr(
        "qdyn.ml_tools.hamgnn_wrapper.multiprocessing.get_context",
        lambda method: dummy_ctx,
    )

    with pytest.raises(RuntimeError, match="Failed to clean up MLSCFSolver resources") as exc_info:
        with MLSCFSolver(
            software="openmx",
            mlh_input=_make_hamgnn_input(batch_size=4),
            model_path=str(model_path),
            logger=SimpleNamespace(),
            nproc=2,
            threads_per_proc=1,
        ):
            raise ValueError("context boom")

    assert isinstance(exc_info.value.__context__, ValueError)
    assert str(exc_info.value.__context__) == "context boom"
    assert dummy_ctx.pool.terminate_calls == 1
    assert dummy_ctx.pool.join_calls == 1
    assert dummy_ctx.manager.shutdown_calls == 1


def test_mlscfsolver_close_failure_terminates_and_shutdowns_manager(
    monkeypatch, tmp_path: Path, hamgnn_wrapper_module
):
    MLSCFSolver = hamgnn_wrapper_module.MLSCFSolver

    model_path = tmp_path / "model.ckpt"
    model_path.write_text("stub", encoding="utf-8")

    class DummyPool:
        def __init__(self):
            self.close_calls = 0
            self.join_calls = 0
            self.terminate_calls = 0

        def close(self):
            self.close_calls += 1
            raise RuntimeError("close boom")

        def join(self):
            self.join_calls += 1

        def terminate(self):
            self.terminate_calls += 1

    class DummyManager:
        def __init__(self):
            self.shutdown_calls = 0

        def Queue(self):
            return Queue()

        def shutdown(self):
            self.shutdown_calls += 1

    class DummyCtx:
        def __init__(self):
            self.pool = DummyPool()
            self.manager = DummyManager()

        def Manager(self):
            return self.manager

        def Pool(self, **kwargs):
            return self.pool

    dummy_ctx = DummyCtx()
    monkeypatch.setattr(
        "qdyn.ml_tools.hamgnn_wrapper.multiprocessing.get_context",
        lambda method: dummy_ctx,
    )

    solver = MLSCFSolver(
        software="openmx",
        mlh_input=_make_hamgnn_input(batch_size=4),
        model_path=str(model_path),
        logger=SimpleNamespace(),
        nproc=2,
        threads_per_proc=1,
    )
    solver.__enter__()

    with pytest.raises(RuntimeError, match="Failed to clean up MLSCFSolver resources"):
        solver.close()

    assert dummy_ctx.pool.close_calls == 1
    assert dummy_ctx.pool.terminate_calls == 1
    assert dummy_ctx.pool.join_calls == 1
    assert dummy_ctx.manager.shutdown_calls == 1

    solver.close()

    assert dummy_ctx.pool.close_calls == 1
    assert dummy_ctx.pool.terminate_calls == 1
    assert dummy_ctx.pool.join_calls == 1
    assert dummy_ctx.manager.shutdown_calls == 1


def test_mlscfsolver_terminate_failure_still_joins_and_shutdowns_manager(
    monkeypatch, tmp_path: Path, hamgnn_wrapper_module
):
    MLSCFSolver = hamgnn_wrapper_module.MLSCFSolver

    model_path = tmp_path / "model.ckpt"
    model_path.write_text("stub", encoding="utf-8")

    class DummyPool:
        def __init__(self):
            self.close_calls = 0
            self.join_calls = 0
            self.terminate_calls = 0

        def close(self):
            self.close_calls += 1

        def join(self):
            self.join_calls += 1

        def terminate(self):
            self.terminate_calls += 1
            raise RuntimeError("terminate boom")

    class DummyManager:
        def __init__(self):
            self.shutdown_calls = 0

        def Queue(self):
            return Queue()

        def shutdown(self):
            self.shutdown_calls += 1

    class DummyCtx:
        def __init__(self):
            self.pool = DummyPool()
            self.manager = DummyManager()

        def Manager(self):
            return self.manager

        def Pool(self, **kwargs):
            return self.pool

    dummy_ctx = DummyCtx()
    monkeypatch.setattr(
        "qdyn.ml_tools.hamgnn_wrapper.multiprocessing.get_context",
        lambda method: dummy_ctx,
    )

    solver = MLSCFSolver(
        software="openmx",
        mlh_input=_make_hamgnn_input(batch_size=4),
        model_path=str(model_path),
        logger=SimpleNamespace(),
        nproc=2,
        threads_per_proc=1,
    )
    solver.__enter__()

    with pytest.raises(RuntimeError, match="Failed to clean up MLSCFSolver resources"):
        solver._cleanup_resources(terminate=True)

    assert dummy_ctx.pool.close_calls == 0
    assert dummy_ctx.pool.terminate_calls == 1
    assert dummy_ctx.pool.join_calls == 1
    assert dummy_ctx.manager.shutdown_calls == 1

    solver.close()

    assert dummy_ctx.pool.terminate_calls == 1
    assert dummy_ctx.pool.join_calls == 1
    assert dummy_ctx.manager.shutdown_calls == 1


def test_init_spawn_worker_populates_orbital_basis(
    monkeypatch, tmp_path: Path, hamgnn_wrapper_module
):
    model_path = tmp_path / "model.ckpt"
    model_path.write_text("stub", encoding="utf-8")

    monkeypatch.setattr(
        "qdyn.ml_tools.hamgnn_wrapper.HamGNNWrapper",
        lambda config, model_path, device="cpu": SimpleNamespace(nao_max=config.nao_max),
    )
    monkeypatch.setattr(
        "qdyn.ml_tools.hamgnn_wrapper.multiprocessing.current_process",
        lambda: SimpleNamespace(_identity=(1,)),
    )
    hamgnn_wrapper_module.ORBITAL_BASIS.clear()

    mlh_input = _make_hamgnn_input(batch_size=4)
    hamgnn_wrapper_module.init_spawn_worker(
        software="openmx",
        mlh_input=mlh_input,
        model_path=str(model_path),
        nproc=1,
        threads_per_proc=1,
        batch_per_proc=2,
        eigen_dtype=hamgnn_wrapper_module.np.float32,
    )

    assert hamgnn_wrapper_module.ORBITAL_BASIS
    assert "S" in hamgnn_wrapper_module.ORBITAL_BASIS


def test_set_spawn_worker_cpu_affinity_uses_pool_worker_index(
    monkeypatch, hamgnn_wrapper_module
):
    affinity_calls = []

    class DummyPsutilProcess:
        def cpu_affinity(self, cpus=None):
            if cpus is None:
                return list(range(8))
            affinity_calls.append(list(cpus))

    psutil_module = ModuleType("psutil")
    psutil_module.Process = DummyPsutilProcess
    monkeypatch.setitem(sys.modules, "psutil", psutil_module)
    monkeypatch.setattr(
        "qdyn.ml_tools.hamgnn_wrapper.multiprocessing.current_process",
        lambda: SimpleNamespace(_identity=(2,)),
    )

    hamgnn_wrapper_module._set_spawn_worker_cpu_affinity(nproc=3, threads_per_proc=2)

    assert affinity_calls == [[2, 3]]


def test_set_spawn_worker_cpu_affinity_raises_when_cpu_range_exceeds_available(
    monkeypatch, hamgnn_wrapper_module
):
    class DummyPsutilProcess:
        def cpu_affinity(self, cpus=None):
            if cpus is None:
                return [0, 1, 2]
            raise AssertionError("cpu_affinity setter should not be called")

    psutil_module = ModuleType("psutil")
    psutil_module.Process = DummyPsutilProcess
    monkeypatch.setitem(sys.modules, "psutil", psutil_module)
    monkeypatch.setattr(
        "qdyn.ml_tools.hamgnn_wrapper.multiprocessing.current_process",
        lambda: SimpleNamespace(_identity=(2,)),
    )

    with pytest.raises(RuntimeError, match="Failed to bind HamGNN spawn worker 2"):
        hamgnn_wrapper_module._set_spawn_worker_cpu_affinity(
            nproc=3,
            threads_per_proc=2,
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

    with solver:
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


def test_mlscfsolver_run_error_terminates_pool_and_shutdowns_manager(
    monkeypatch, tmp_path: Path, hamgnn_wrapper_module
):
    from ase import Atoms
    MLSCFSolver = hamgnn_wrapper_module.MLSCFSolver

    model_path = tmp_path / "model.ckpt"
    model_path.write_text("stub", encoding="utf-8")

    class DummyResult:
        def ready(self):
            return True

        def get(self):
            raise ValueError("worker boom")

    class DummyPool:
        def __init__(self):
            self.close_calls = 0
            self.join_calls = 0
            self.terminate_calls = 0

        def apply_async(self, func, args):
            return DummyResult()

        def close(self):
            self.close_calls += 1

        def join(self):
            self.join_calls += 1

        def terminate(self):
            self.terminate_calls += 1

    class DummyManager:
        def __init__(self):
            self.shutdown_calls = 0

        def Queue(self):
            return Queue()

        def shutdown(self):
            self.shutdown_calls += 1

    class DummyCtx:
        def __init__(self):
            self.pool = DummyPool()
            self.manager = DummyManager()

        def Manager(self):
            return self.manager

        def Pool(self, processes, initializer=None, initargs=()):
            return self.pool

    dummy_ctx = DummyCtx()
    monkeypatch.setattr(
        "qdyn.ml_tools.hamgnn_wrapper.multiprocessing.get_context",
        lambda method: dummy_ctx,
    )
    monkeypatch.setattr("qdyn.ml_tools.hamgnn_wrapper.time.sleep", lambda _: None)

    solver = MLSCFSolver(
        software="openmx",
        mlh_input=_make_hamgnn_input(batch_size=2),
        model_path=str(model_path),
        logger=SimpleNamespace(),
        nproc=1,
        threads_per_proc=1,
    )

    solver.tasks = [
        (0, tmp_path / "scf_0001", Atoms("H", positions=[[0.0, 0.0, 0.0]])),
    ]
    solver.task_count = 1

    with pytest.raises(RuntimeError, match="MLSCFSolver.run failed: worker boom"):
        with solver:
            solver.run()

    assert dummy_ctx.pool.terminate_calls == 1
    assert dummy_ctx.pool.join_calls == 1
    assert dummy_ctx.pool.close_calls == 0
    assert dummy_ctx.manager.shutdown_calls == 1
    assert solver.tasks == []
    assert solver.task_count == 0

    solver.close()

    assert dummy_ctx.pool.terminate_calls == 1
    assert dummy_ctx.pool.join_calls == 1
    assert dummy_ctx.manager.shutdown_calls == 1
