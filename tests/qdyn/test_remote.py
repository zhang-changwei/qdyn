from pathlib import Path
from types import SimpleNamespace

import pytest

from qdyn.errors import ConfigError
from qdyn.frontend_api.run_dir_access import LocalRunDirAccess, RemoteRunDirAccess
from qdyn.pool import WorkerPool


class DummyHost:
    def __init__(self):
        self.mkdir_calls: list[tuple[str, bool, bool]] = []
        self.put_calls: list[tuple[str, str]] = []
        self.commands: list[str] = []

    def mkdir(self, directory: str, recursive: bool = True, exist_ok: bool = True):
        self.mkdir_calls.append((directory, recursive, exist_ok))
        return True

    def put(self, src: str, dst: str):
        self.put_calls.append((src, dst))

    def execute(self, cmd: str):
        self.commands.append(cmd)
        if cmd.startswith("test -f "):
            return "", "", 1
        if cmd.startswith("rm -f "):
            return "", "", 0
        if cmd.startswith("python -c ") or "python -c " in cmd:
            return "{}", "", 0
        return "ok", "", 0


def _make_pool(pool_name: str, worker_type: str, user_data: str) -> WorkerPool:
    jc = SimpleNamespace(
        jobs=SimpleNamespace(aggregate=lambda pipeline: []),
        project=object(),
        get_job_info=lambda job_id: None,
    )
    config = {
        "worker_pools": {
            pool_name: {
                "pool": {"user_data": user_data, "size": 1, "work_dir_base": "/runs"},
                "worker": {
                    "type": worker_type,
                    "installed": {"python": True},
                    "modules": {"python": []},
                    "export": {"python": {}},
                    "pre_run": {"python": ""},
                },
            }
        }
    }
    jf_config = {
        "workers": {
            f"{pool_name}_001": {
                "type": worker_type,
                "work_dir": "/runs/001",
                "host": "remote.example.com",
            }
        }
    }
    return WorkerPool(
        job_controller=jc,
        pool_name=pool_name,
        config=config,
        jf_config=jf_config,
    )


def test_upload_user_file_remote_uses_host_mkdir_and_put(tmp_path: Path, monkeypatch):
    local_path = tmp_path / "traj.xyz"
    local_path.write_text("test", encoding="utf-8")

    pool = _make_pool("remote_pool", "remote", "/remote/user_data")
    host = DummyHost()
    monkeypatch.setattr(pool, "_get_remote_host", lambda worker_name: host)

    remote_path = pool.upload_user_file(
        file_type="trajectory",
        local_path=local_path,
        file_hash="traj-hash",
    )

    assert remote_path == "/remote/user_data/trajectory/traj-hash"
    assert host.mkdir_calls == [("/remote/user_data/trajectory", True, True)]
    assert host.put_calls == [(str(local_path), "/remote/user_data/trajectory/traj-hash")]


def test_upload_user_file_remote_wraps_errors(tmp_path: Path, monkeypatch):
    local_path = tmp_path / "traj.xyz"
    local_path.write_text("test", encoding="utf-8")

    class FailingHost(DummyHost):
        def put(self, src: str, dst: str):
            raise RuntimeError("upload failed")

    pool = _make_pool("remote_pool", "remote", "/remote/user_data")
    monkeypatch.setattr(pool, "_get_remote_host", lambda worker_name: FailingHost())

    with pytest.raises(ConfigError, match="Failed to upload file to remote worker pool"):
        pool.upload_user_file(
            file_type="trajectory",
            local_path=local_path,
            file_hash="traj-hash",
        )


def test_build_run_dir_access_creates_remote_access(monkeypatch):
    pool = _make_pool("remote_pool", "remote", "/remote/user_data")
    host = DummyHost()
    pool.jc.get_job_info = lambda job_id: SimpleNamespace(
        run_dir="/remote/run",
        worker="remote_pool_001",
    )

    monkeypatch.setattr(pool, "_get_shared_host", lambda project, worker_name: host)

    access = pool.build_run_dir_access("job-123")

    assert isinstance(access, RemoteRunDirAccess)
    assert access.run_dir_path == "/remote/run"


def test_build_run_dir_access_creates_local_access(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    pool = _make_pool("local_slurm", "local", str(tmp_path / "user_data"))
    pool.jc.get_job_info = lambda job_id: SimpleNamespace(
        run_dir=str(run_dir),
        worker="local_slurm_001",
    )

    access = pool.build_run_dir_access("job-123")

    assert isinstance(access, LocalRunDirAccess)
    assert access.run_dir_path == str(run_dir)


def test_get_user_file_path_uses_pool_user_data_remote():
    pool = _make_pool("remote_pool", "remote", "/remote/user_data")

    assert pool.get_user_file_path("trajectory", "abc123") == "/remote/user_data/trajectory/abc123"


def test_get_user_file_path_uses_local_path_semantics(tmp_path: Path):
    pool = _make_pool("local_slurm", "local", str(tmp_path))

    assert pool.get_user_file_path("trajectory", "abc123") == str(tmp_path / "trajectory" / "abc123")
