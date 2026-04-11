from pathlib import Path

from qdyn.frontend_api.run_dir_access import RemoteRunDirAccess


class DummyRemoteHost:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.get_calls: list[tuple[str, str]] = []
        self.execute_calls: list[str] = []

    def get(self, src: str, dst: str) -> None:
        self.get_calls.append((src, dst))
        raise RuntimeError("Garbage packet received")

    def execute(self, cmd: str):
        import base64

        self.execute_calls.append(cmd)
        return base64.b64encode(self.payload).decode("ascii"), "", 0


def test_remote_download_root_file_prefers_exec_base64(tmp_path: Path):
    host = DummyRemoteHost(b"png-bytes")
    access = RemoteRunDirAccess("/remote/run_dir", host)

    data = access.download_root_file("figure.png")

    assert data == b"png-bytes"
    assert host.execute_calls
    assert host.get_calls == []
    assert "python3 -c" in host.execute_calls[0]


def test_remote_download_subdir_file_prefers_exec_base64(tmp_path: Path):
    host = DummyRemoteHost(b"subdir-bytes")
    access = RemoteRunDirAccess("/remote/run_dir", host)

    data = access.download_subdir_file("scf_001", "OUTCAR")

    assert data == b"subdir-bytes"
    assert host.execute_calls
    assert host.get_calls == []


class ExecFailingRemoteHost(DummyRemoteHost):
    def execute(self, cmd: str):
        self.execute_calls.append(cmd)
        raise RuntimeError("ssh exec failed")

    def get(self, src: str, dst: str) -> None:
        self.get_calls.append((src, dst))
        Path(dst).write_bytes(self.payload)


def test_remote_download_root_file_falls_back_to_sftp_when_exec_fails(tmp_path: Path):
    host = ExecFailingRemoteHost(b"png-bytes")
    access = RemoteRunDirAccess("/remote/run_dir", host)

    data = access.download_root_file("figure.png")

    assert data == b"png-bytes"
    assert host.execute_calls
    assert host.get_calls
