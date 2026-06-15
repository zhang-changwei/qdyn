from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from contextlib import redirect_stdout

import pytest

from scripts import download_pretrained_models as script


def test_pretrained_model_filenames_match_params():
    assert script.nequip_pretrained_model_filename(
        "mir-group/NequIP-OAM-L", "cuda"
    ) == "mir-group__NequIP-OAM-L_cuda__0.1.nequip.pth"
    assert script.mace_pretrained_model_filename("small") == "2023-12-10-mace-128-L0_energy_epoch-249.model"


def test_download_script_downloads_selected_targets(monkeypatch, tmp_path: Path):
    root = tmp_path / ".qdyn" / "pretrained"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(script, "PRETRAINED_ROOT", root)

    calls: list[tuple[str, str]] = []

    def fake_nequip(model_name: str, device: str) -> Path:
        target = root / script.nequip_pretrained_model_filename(model_name, device)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("nequip", encoding="utf-8")
        calls.append((model_name, device))
        return target

    def fake_mace(model_name: str) -> Path:
        target = root / script.mace_pretrained_model_filename(model_name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("mace", encoding="utf-8")
        calls.append((model_name, "mace"))
        return target

    monkeypatch.setattr(script, "_download_nequip_model", fake_nequip)
    monkeypatch.setattr(script, "_download_mace_model", fake_mace)

    rc = script.main([
        "--nequip-model",
        "mir-group/NequIP-OAM-L",
        "--mace-model",
        "small",
        "--nequip-device",
        "cpu",
    ])

    assert rc == 0
    assert (root / "mir-group__NequIP-OAM-L_cpu__0.1.nequip.pth").is_file()
    assert (root / "2023-12-10-mace-128-L0_energy_epoch-249.model").is_file()
    assert calls == [
        ("mir-group/NequIP-OAM-L", "cpu"),
        ("small", "mace"),
    ]


def test_download_script_lists_supported_models():
    stdout = io.StringIO()

    with redirect_stdout(stdout):
        rc = script.main(["--list-models"])

    output = stdout.getvalue()
    assert rc == 0
    assert "NequIP:" in output
    assert "mir-group/NequIP-OAM-L" in output
    assert "MACE:" in output
    assert "medium-0b3" in output


def test_validate_nve_input_checks_mace_pretrained_model_path():
    try:
        from qdyn.input import MACEInputT, NVEInputT
        from qdyn.validation import validate_nve_input
    except ImportError as exc:
        pytest.skip(f"runtime dependencies unavailable: {exc}")

    nve = NVEInputT(
        software="mace",
        calculator=MACEInputT(
            use_gpu=False,
            use_pretrained_model=True,
            model_name="medium-0b3",
        ),
    )
    worker_cfg = {"gpu_resources": None}
    pool = SimpleNamespace(
        check_file_exists=lambda path: path.endswith("mace-mp-0b3-medium.model"),
        user_file_exists=lambda *_: False,
    )
    check_list = {"gpu": False, "models": []}

    validate_nve_input(nve, pool, worker_cfg, check_list)

    assert check_list["models"] == ["medium-0b3"]


def test_validate_nve_input_rejects_missing_mace_pretrained_model():
    try:
        from qdyn.input import MACEInputT, NVEInputT
        from qdyn.validation import ValidationError, validate_nve_input
    except ImportError as exc:
        pytest.skip(f"runtime dependencies unavailable: {exc}")

    nve = NVEInputT(
        software="mace",
        calculator=MACEInputT(
            use_gpu=False,
            use_pretrained_model=True,
            model_name="medium-0b3",
        ),
    )
    worker_cfg = {"gpu_resources": None}
    pool = SimpleNamespace(
        check_file_exists=lambda path: False,
        user_file_exists=lambda *_: False,
    )

    with pytest.raises(ValidationError, match="medium-0b3"):
        validate_nve_input(nve, pool, worker_cfg, {"gpu": False, "models": []})


def test_workerpool_check_file_exists_expands_home_on_remote():
    try:
        from qdyn.pool import WorkerPool
    except ImportError as exc:
        pytest.skip(f"runtime dependencies unavailable: {exc}")

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
