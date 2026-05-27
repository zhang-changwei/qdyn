from __future__ import annotations

from pathlib import Path
from queue import Queue
from types import SimpleNamespace

import pytest


def _make_hamgnn_input(batch_size: int = 4):
    return SimpleNamespace(
        batch_size=batch_size,
        add_H0=False,
        nao_max=13,
        adv=SimpleNamespace(eigen_dtype="float32"),
    )


def test_mlscfsolver_rejects_non_linux(monkeypatch, tmp_path: Path):
    from qdyn.ml_tools.hamgnn_wrapper import MLSCFSolver

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


def test_mlscfsolver_run_chunks_tasks_and_logs_progress(monkeypatch, tmp_path: Path):
    from ase import Atoms
    from qdyn.ml_tools.hamgnn_wrapper import MLSCFSolver

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
                    {"type": "step_done", "step": step, "task_dir": task_dir}
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

        def Pool(self, processes):
            return self._pool

        def Queue(self):
            return Queue()

    logger_calls = []

    monkeypatch.setattr("qdyn.ml_tools.hamgnn_wrapper.sys.platform", "linux")
    monkeypatch.setattr(
        "qdyn.ml_tools.hamgnn_wrapper._configure_worker_threads",
        lambda omp: None,
    )
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
        (0, "scf_0001", "ml"),
        (2, "scf_0003", "ml"),
        (1, "scf_0002", "ml"),
        (3, "scf_0004", "ml"),
    ]
