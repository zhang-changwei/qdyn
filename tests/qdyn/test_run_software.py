from __future__ import annotations

import io
from pathlib import Path

from qdyn.pool import WorkerPool
from qdyn.tools.run_software import DFTStatus, MDProgressMonitor, run_vasp


def test_workerpool_check_file_exists_replaces_home_prefix():
    captured: dict[str, str] = {}

    class DummyHost:
        def execute(self, cmd: str):
            captured["cmd"] = cmd
            return "ok", "", 0

    pool = WorkerPool.__new__(WorkerPool)
    pool._remote = True
    pool._workers = ["remote_pool_001"]
    pool.get_pool_workers = lambda jf_config=None: ["remote_pool_001"]  # type: ignore[method-assign]
    pool._get_remote_host = lambda worker_name: DummyHost()  # type: ignore[method-assign]

    assert pool.check_file_exists("~/.qdyn/pretrained/test.model") is True
    assert captured["cmd"] == 'test -f "$HOME/.qdyn/pretrained/test.model" && echo ok'


def test_md_progress_monitor_accepts_first_valid_step_without_prev_line():
    monitor = MDProgressMonitor("vasp", nstep=10, check_convergence=True)
    monitor_file = io.StringIO("1 0 300.0 3 4 5 6 7 -10.0 9 1.5 T=\n")
    log_file = io.StringIO()

    assert monitor.monitor_vasp(monitor_file, log_file) == DFTStatus.NORMAL
    assert log_file.getvalue().startswith("0.0010")


def test_md_progress_monitor_uses_d_eps_not_ncg_for_convergence_check():
    monitor = MDProgressMonitor("vasp", nstep=10, scf_thr=1e-5, check_convergence=True)
    monitor.prev_line = (
        "DAV:   7    -0.814807001502E+03   -0.45219E-06"
        "   -0.28315E-06   672   0.277E-03\n"
    )
    monitor_file = io.StringIO("1 0 300.0 3 4 5 6 7 -10.0 9 1.5 T=\n")
    log_file = io.StringIO()

    assert monitor.monitor_vasp(monitor_file, log_file) == DFTStatus.NORMAL
    assert log_file.getvalue().startswith("0.0010")


def test_run_vasp_calls_monitor_after_process_exit(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "KPOINTS").write_text("kpoints\n0\nGamma\n1 1 1\n", encoding="utf-8")

    calls: list[str] = []

    class DummyProcess:
        def __init__(self):
            self.poll_count = 0

        def poll(self):
            self.poll_count += 1
            return None if self.poll_count == 1 else 0

        def wait(self):
            return 0

        def terminate(self):
            calls.append("terminate")

    monkeypatch.setattr(
        "qdyn.tools.run_software.subprocess.Popen",
        lambda *args, **kwargs: DummyProcess(),
    )
    monkeypatch.setattr("qdyn.tools.run_software.time.sleep", lambda *_: None)
    monitor = lambda: calls.append("monitor") or DFTStatus.NORMAL

    run_vasp(1, monitor=monitor)

    assert calls == ["monitor", "monitor"]
