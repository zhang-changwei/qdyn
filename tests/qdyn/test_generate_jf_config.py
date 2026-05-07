import hashlib
import subprocess
import sys
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_jf_config.py"


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_generate_jf_config_writes_hash_back_to_qdyn(tmp_path: Path):
    output_path = tmp_path / "jf_qdyn.yaml"
    qdyn_path = tmp_path / "qdyn.yaml"
    jf_base_path = tmp_path / "jf_base.yaml"

    qdyn_path.write_text(
        (
            "basic:\n"
            f"  jf_project_path: {output_path.as_posix()}\n"
            "  jf_project_name: jf_qdyn\n"
            "active_pool: local_slurm\n"
            "worker_pools:\n"
            "  local_slurm:\n"
            "    pool:\n"
            "      size: 1\n"
            "      work_dir_base: /tmp/runs\n"
            "    worker:\n"
            "      type: local\n"
            "      scheduler_type: slurm\n"
        ),
        encoding="utf-8",
    )
    jf_base_path.write_text(
        (
            "name: jf_qdyn\n"
            "queue: {}\n"
            "jobstore: {}\n"
            "runner: {}\n"
        ),
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--qdyn-config",
            str(qdyn_path),
            "--jf-base",
            str(jf_base_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    updated_qdyn = yaml.safe_load(qdyn_path.read_text(encoding="utf-8"))

    assert output_path.is_file()
    assert updated_qdyn["basic"]["jf_config_hash"] == _file_sha256(output_path)
