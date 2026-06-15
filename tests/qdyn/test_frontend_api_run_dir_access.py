from pathlib import Path

from qdyn.frontend_api.run_dir_access import LocalRunDirAccess, RemoteRunDirAccess


def test_local_scan_scf_status_uses_log_categories_only(tmp_path: Path):
    """Local scan derives status exclusively from qdyn_scf.log categories.

    Product files (WAVECAR, OUTCAR, wfc.npz) and marker files (FAIL, ENDED,
    RUNNING) do NOT influence the result; only log category records matter.

    Category mapping:
      normal / posthamgnn / overlap  -> ENDED
      prehamgnn / hamgnn             -> RUNNING  (ENDED takes priority)
      no log record                  -> PENDING
    """
    (tmp_path / "qdyn_scf.log").write_text(
        "\n".join(
            [
                "Step: 6, Interval: 1",
                "Step     Global_idx     Category",
                "0        scf_002        normal",
                "1        scf_003        prehamgnn",
                "2        scf_003        hamgnn",
                "3        scf_004        posthamgnn",
                "4        scf_005        overlap",
            ]
        ),
        encoding="utf-8",
    )

    # scf_001: has FAIL marker and WAVECAR but no log record -> PENDING
    no_log_dir = tmp_path / "scf_001"
    no_log_dir.mkdir()
    (no_log_dir / "FAIL").write_text("failed", encoding="utf-8")
    (no_log_dir / "WAVECAR").write_text("wave", encoding="utf-8")

    # scf_002: log category 'normal' -> ENDED (has POSCAR but irrelevant)
    normal_dir = tmp_path / "scf_002"
    normal_dir.mkdir()
    (normal_dir / "POSCAR").write_text("input", encoding="utf-8")

    # scf_003: log category 'hamgnn' (only intermediate) -> RUNNING
    # even though it has WAVECAR and OUTCAR; products are ignored
    running_dir = tmp_path / "scf_003"
    running_dir.mkdir()
    (running_dir / "WAVECAR").write_text("wave", encoding="utf-8")
    (running_dir / "OUTCAR").write_text(
        "Total CPU\naborting loop because EDIFF is reached\n",
        encoding="utf-8",
    )

    # scf_004: log category 'posthamgnn' -> ENDED
    posthamgnn_dir = tmp_path / "scf_004"
    posthamgnn_dir.mkdir()
    (posthamgnn_dir / "wfc.npz").write_bytes(b"wfc")

    # scf_005: log category 'overlap' -> ENDED
    overlap_dir = tmp_path / "scf_005"
    overlap_dir.mkdir()
    (overlap_dir / "POSCAR").write_text("input", encoding="utf-8")

    # scf_006: no log record -> PENDING regardless of POSCAR
    pending_dir = tmp_path / "scf_006"
    pending_dir.mkdir()
    (pending_dir / "POSCAR").write_text("input", encoding="utf-8")

    status = LocalRunDirAccess(tmp_path).scan_scf_status()

    # scf_001: marker/product irrelevant, no log record -> PENDING
    assert status["scf_001"].status == "PENDING"
    # scf_002: 'normal' category -> ENDED
    assert status["scf_002"].status == "ENDED"
    # scf_003: only intermediate categories -> RUNNING
    assert status["scf_003"].status == "RUNNING"
    # scf_004: 'posthamgnn' category -> ENDED
    assert status["scf_004"].status == "ENDED"
    # scf_005: 'overlap' category -> ENDED
    assert status["scf_005"].status == "ENDED"
    # scf_006: no log record -> PENDING
    assert status["scf_006"].status == "PENDING"


def test_local_scan_scf_status_without_log_all_pending(tmp_path: Path):
    """Without qdyn_scf.log every existing scf_* subdir is PENDING."""
    for name in ("scf_001", "scf_002"):
        d = tmp_path / name
        d.mkdir()
        (d / "POSCAR").write_text("input", encoding="utf-8")

    status = LocalRunDirAccess(tmp_path).scan_scf_status()

    assert status["scf_001"].status == "PENDING"
    assert status["scf_002"].status == "PENDING"


def test_local_scan_scf_status_ended_beats_running_same_frame(tmp_path: Path):
    """ENDED takes priority over RUNNING for the same frame."""
    (tmp_path / "qdyn_scf.log").write_text(
        "\n".join(
            [
                "Step: 2, Interval: 1",
                "Step     Global_idx     Category",
                "0        scf_001        prehamgnn",
                "1        scf_001        posthamgnn",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "scf_001").mkdir()

    status = LocalRunDirAccess(tmp_path).scan_scf_status()

    assert status["scf_001"].status == "ENDED"


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


class ScanRemoteHost(DummyRemoteHost):
    def __init__(self):
        super().__init__(b"")

    def execute(self, cmd: str):
        self.execute_calls.append(cmd)
        return "scf_001\tENDED\t3\n", "", 0


def test_remote_scan_scf_status_uses_log_categories_not_products():
    """Remote scan uses qdyn_scf.log + awk; no product-file probing."""
    host = ScanRemoteHost()
    access = RemoteRunDirAccess("/remote/run_dir", host)

    status = access.scan_scf_status()

    assert status["scf_001"].status == "ENDED"
    cmd = host.execute_calls[0]

    # Must contain log-based detection keywords.
    assert "qdyn_scf.log" in cmd
    assert "awk" in cmd
    assert "normal" in cmd
    assert "posthamgnn" in cmd
    assert "overlap" in cmd
    assert "prehamgnn" in cmd
    assert "hamgnn" in cmd
    assert 'find "$d" -maxdepth 1 -type f' in cmd

    # Must NOT probe product files.
    assert "WAVECAR" not in cmd
    assert "OUTCAR" not in cmd
    assert "OSZICAR" not in cmd
    assert "wfc.npz" not in cmd
    assert "Elapsed.Time." not in cmd
    assert 'grep -q "Total CPU"' not in cmd
