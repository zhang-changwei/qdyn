from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

from qdyn.frontend_api.service import (
    _detect_step_type,
    _dt_str,
    _flatten_parameter_mapping,
    get_job_progress,
    get_job_input_params,
)


def test_dt_str_marks_naive_datetime_as_utc():
    assert _dt_str(datetime(2026, 4, 2, 12, 28, 9)) == "2026-04-02T12:28:09Z"


def test_dt_str_preserves_explicit_timezone():
    assert _dt_str(datetime(2026, 4, 2, 20, 28, 9, tzinfo=timezone.utc)) == "2026-04-02T20:28:09Z"


def test_dt_str_adds_utc_suffix_to_naive_iso_string():
    assert _dt_str("2026-04-02T12:28:09") == "2026-04-02T12:28:09Z"


def test_detect_step_type_distinguishes_pre_namd_from_namd():
    assert _detect_step_type("qdyn_pre_namd") == "pre_namd"
    assert _detect_step_type("qdyn_namd") == "namd"


def test_flatten_parameter_mapping_handles_nested_values():
    flattened = _flatten_parameter_mapping(
        {
            "bmin": "VBM-1",
            "adv": {
                "reorder": False,
                "which_atoms": [1, 2, 5],
                "@module": "qdyn.input",
            },
        }
    )

    assert flattened == {
        "bmin": "VBM-1",
        "adv.reorder": "false",
        "adv.which_atoms": "1, 2, 5",
    }


def test_get_job_input_params_reads_prenamd_parameters_from_jfremote_json(
    monkeypatch, tmp_path: Path
):
    run_dir = tmp_path / "prenamd_job"
    run_dir.mkdir()
    (run_dir / "jfremote_in.json").write_text(
        json.dumps(
            {
                "job": {
                    "function_kwargs": {
                        "parameters": {
                            "bmin": "VBM-1",
                            "bmax": "CBM+2",
                            "surface_hopping": "DISH",
                            "adv": {
                                "reorder": True,
                                "which_atoms": [3, 8],
                            },
                        }
                    }
                }
            }
        )
    )

    class DummyJobInfo:
        name = "qdyn_pre_namd"

    class DummyManager:
        def get_task_pool(self, task_id: str):
            assert task_id == "task-1"
            return SimpleNamespace(
                build_run_dir_access=lambda job_uuid: LocalRunDirAccess(run_dir)
            )

        def get_job_info(self, job_uuid: str):
            assert job_uuid == "job-123"
            return DummyJobInfo()

    from qdyn.frontend_api.run_dir_access import LocalRunDirAccess

    response = get_job_input_params(DummyManager(), "task-1", "job-123")

    assert response.available is True
    assert response.parameters_title == "PRE_NAMD Parameters"
    assert response.parameters == {
        "bmin": "VBM-1",
        "bmax": "CBM+2",
        "surface_hopping": "DISH",
        "adv.reorder": "true",
        "adv.which_atoms": "3, 8",
    }
    assert response.warning is None


def test_get_job_input_params_prefers_jfremote_json_for_scf(tmp_path: Path):
    run_dir = tmp_path / "scf_job"
    run_dir.mkdir()
    (run_dir / "INCAR").write_text("ENCUT = 500\n")
    (run_dir / "KPOINTS").write_text("kpoints\n0\nGamma\n1 1 1\n")
    (run_dir / "jfremote_in.json").write_text(
        json.dumps(
            {
                "job": {
                    "function_kwargs": {
                        "parameters": {
                            "software": "openmx",
                            "scf": {"criterion": 1e-6},
                        }
                    }
                }
            }
        )
    )

    class DummyJobInfo:
        name = "qdyn_scf"

    class DummyManager:
        def get_task_pool(self, task_id: str):
            assert task_id == "task-1"
            return SimpleNamespace(
                build_run_dir_access=lambda job_uuid: LocalRunDirAccess(run_dir)
            )

        def get_job_info(self, job_uuid: str):
            assert job_uuid == "job-123"
            return DummyJobInfo()

    from qdyn.frontend_api.run_dir_access import LocalRunDirAccess

    response = get_job_input_params(DummyManager(), "task-1", "job-123")

    assert response.available is True
    assert response.parameters_title == "SCF Parameters"
    assert response.parameters == {
        "software": "openmx",
        "scf.criterion": "1e-06",
    }
    assert response.incar is None
    assert response.kpoints_text is None
    assert response.warning is None


def test_get_job_input_params_falls_back_to_vasp_files(tmp_path: Path):
    run_dir = tmp_path / "nvt_job"
    run_dir.mkdir()
    (run_dir / "INCAR").write_text("ENCUT = 500\nISMEAR = 0\n")
    (run_dir / "KPOINTS").write_text("kpoints\n0\nGamma\n1 1 1\n")

    class DummyJobInfo:
        name = "qdyn_nvt"

    class DummyManager:
        def get_task_pool(self, task_id: str):
            assert task_id == "task-1"
            return SimpleNamespace(
                build_run_dir_access=lambda job_uuid: LocalRunDirAccess(run_dir)
            )

        def get_job_info(self, job_uuid: str):
            assert job_uuid == "job-123"
            return DummyJobInfo()

    from qdyn.frontend_api.run_dir_access import LocalRunDirAccess

    response = get_job_input_params(DummyManager(), "task-1", "job-123")

    assert response.available is True
    assert response.parameters is None
    assert response.incar == {"ENCUT": "500", "ISMEAR": "0"}
    assert response.kpoints_text == "kpoints\n0\nGamma\n1 1 1\n"
    assert response.warning is None


def test_get_job_progress_hides_placeholder_progress_for_namd(monkeypatch, tmp_path: Path):
    run_dir = tmp_path / "namd_job"
    run_dir.mkdir()

    class DummyState:
        value = "RUNNING"

    class DummyJobInfo:
        name = "qdyn_namd"
        state = DummyState()

    DummyJobInfo.run_dir = str(run_dir)

    class DummyJobController:
        def get_job_info(self, job_id: str):
            assert job_id == "job-123"
            return DummyJobInfo()

    class DummyManager:
        def get_task_pool(self, task_id: str):
            assert task_id == "task-1"
            return SimpleNamespace(
                build_run_dir_access=lambda job_uuid: LocalRunDirAccess(run_dir)
            )

        def _ensure_job_controller(self):
            return DummyJobController()

    from qdyn.frontend_api.run_dir_access import LocalRunDirAccess

    response = get_job_progress(DummyManager(), "task-1", "job-123")

    assert response.available is False
    assert response.step_type == "namd"
    assert response.current_step == 0
