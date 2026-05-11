#!/usr/bin/env python3
"""Download pretrained NequIP/MACE base models into ~/.qdyn/pretrained."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parents[1]
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from qdyn.params import (
    MACE_PRETRAINED_MODEL_URLS,
    MACE_PRETRAINED_MODELS,
    NEQUIP_PRETRAINED_MODELS,
)
from qdyn.tools.mlff_wrapper import (
    mace_pretrained_model_filename,
    nequip_pretrained_model_filename,
)

PRETRAINED_ROOT = Path("~/.qdyn/pretrained").expanduser()


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _download_file(url: str, target_path: Path) -> None:
    _ensure_parent(target_path)
    with tempfile.NamedTemporaryFile(
        delete=False,
        dir=str(target_path.parent),
        prefix=f".{target_path.name}.",
        suffix=".tmp",
    ) as tmp:
        tmp_path = Path(tmp.name)
    try:
        with urllib.request.urlopen(url) as response, open(tmp_path, "wb") as fh:
            shutil.copyfileobj(response, fh)
        tmp_path.replace(target_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _download_nequip_model(model_name: str, device: str) -> Path:
    target = PRETRAINED_ROOT / nequip_pretrained_model_filename(model_name, device)
    if target.is_file():
        return target

    _ensure_parent(target)
    cmd = [
        "nequip-compile",
        f"nequip.net:{model_name}:0.1",
        target.name,
        "--mode",
        "aotinductor",
        "--device",
        device,
        "--target",
        "ase",
    ]
    if shutil.which("nequip-compile") is None:
        cmd = [
            sys.executable,
            "-m",
            "nequip.scripts.nequip_compile",
            f"nequip.net:{model_name}:0.1",
            target.name,
            "--mode",
            "aotinductor",
            "--device",
            device,
            "--target",
            "ase",
        ]
    subprocess.run(cmd, cwd=str(target.parent), check=True)
    return target


def _download_mace_model(model_name: str) -> Path:
    target = PRETRAINED_ROOT / mace_pretrained_model_filename(model_name)
    if target.is_file():
        return target
    _download_file(MACE_PRETRAINED_MODEL_URLS[model_name], target)
    return target


def _selected_families(args: argparse.Namespace) -> tuple[bool, bool]:
    download_all = args.all or (
        not args.nequip_model and not args.mace_model
    )
    return (
        download_all or bool(args.nequip_model),
        download_all or bool(args.mace_model),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download pretrained NequIP and MACE models into ~/.qdyn/pretrained.",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List all supported pretrained model names and exit.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Download all supported pretrained models.",
    )
    parser.add_argument(
        "--nequip-model",
        action="append",
        choices=NEQUIP_PRETRAINED_MODELS,
        help="Download only the selected NequIP model(s). Repeatable.",
    )
    parser.add_argument(
        "--nequip-device",
        action="append",
        choices=["cpu", "cuda"],
        help="NequIP device variant(s) to download. Defaults to both.",
    )
    parser.add_argument(
        "--mace-model",
        action="append",
        choices=MACE_PRETRAINED_MODELS,
        help="Download only the selected MACE MP model(s). Repeatable.",
    )
    args = parser.parse_args(argv)

    if args.list_models:
        print("NequIP:")
        for model_name in NEQUIP_PRETRAINED_MODELS:
            print(f"  {model_name}")
        print("MACE:")
        for model_name in MACE_PRETRAINED_MODELS:
            print(f"  {model_name}")
        return 0

    nequip_enabled, mace_enabled = _selected_families(args)
    nequip_models = args.nequip_model or list(NEQUIP_PRETRAINED_MODELS)
    nequip_devices = args.nequip_device or ["cpu", "cuda"]
    mace_models = args.mace_model or list(MACE_PRETRAINED_MODELS)

    PRETRAINED_ROOT.mkdir(parents=True, exist_ok=True)

    downloaded: list[str] = []
    if nequip_enabled:
        for model_name in nequip_models:
            for device in nequip_devices:
                target = _download_nequip_model(model_name, device)
                downloaded.append(str(target))
    if mace_enabled:
        for model_name in mace_models:
            target = _download_mace_model(model_name)
            downloaded.append(str(target))

    for item in downloaded:
        print(item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
