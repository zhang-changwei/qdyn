from pathlib import Path

from qdyn.frontend_api.run_dir_access import LocalRunDirAccess
from qdyn.frontend_api.service import (
    _get_scf_progress,
    _get_scf_progress_from_log_text,
)


def test_scf_progress_log_counts_only_completed_categories():
    """prehamgnn/hamgnn/posthamgnn all in one frame -> completed=1, running=0."""
    progress = _get_scf_progress_from_log_text(
        "\n".join(
            [
                "Step: 3, Interval: 1",
                "Step     Global_idx     Category",
                "0        scf_001        prehamgnn",
                "0        scf_001        hamgnn",
                "0        scf_001        posthamgnn",
                "1        scf_002        prehamgnn",
            ]
        )
    )

    assert progress.total_steps == 3
    assert progress.current_step == 1
    assert progress.batch is not None
    assert progress.batch.completed == 1
    # scf_002 has only prehamgnn -> RUNNING
    assert progress.batch.running == 1
    assert progress.batch.pending == 1
    assert progress.current_frame is not None
    assert progress.current_frame.name == "scf_002"


def test_scf_progress_log_intermediate_only_is_running():
    """Frame with only prehamgnn category counts as running, not completed."""
    progress = _get_scf_progress_from_log_text(
        "\n".join(
            [
                "Step: 2, Interval: 1",
                "Step     Global_idx     Category",
                "0        scf_001        normal",
                "1        scf_002        hamgnn",
            ]
        )
    )

    assert progress.batch is not None
    assert progress.batch.completed == 1
    assert progress.batch.running == 1
    assert progress.batch.pending == 0
    assert progress.current_frame is not None
    assert progress.current_frame.name == "scf_002"
    # Electronic step fields must be None (not read from VASP files)
    assert progress.current_frame.electronic_step_current is None
    assert progress.current_frame.electronic_step_limit is None
    assert progress.current_frame.scf_algorithm is None
    assert progress.current_frame.converged is None


def test_scf_progress_log_no_running_record_is_pending():
    """Frames with no log record are PENDING; 'next frame after completed' is NOT auto-running."""
    progress = _get_scf_progress_from_log_text(
        "\n".join(
            [
                "Step: 3, Interval: 1",
                "Step     Global_idx     Category",
                "0        scf_001        normal",
            ]
        )
    )

    assert progress.batch is not None
    assert progress.batch.completed == 1
    # scf_002 has no record -> PENDING (NOT inferred as running)
    assert progress.batch.running == 0
    assert progress.batch.pending == 2
    assert progress.current_frame is None


def test_scf_progress_log_ended_beats_running_same_frame():
    """ENDED takes priority when the same frame has both intermediate and completed categories."""
    progress = _get_scf_progress_from_log_text(
        "\n".join(
            [
                "Step: 1, Interval: 1",
                "Step     Global_idx     Category",
                "0        scf_001        prehamgnn",
                "1        scf_001        posthamgnn",
            ]
        )
    )

    assert progress.batch is not None
    assert progress.batch.completed == 1
    assert progress.batch.running == 0
    assert progress.batch.pending == 0
    assert progress.current_frame is None


def test_scf_progress_uses_log_as_primary_source(tmp_path: Path):
    """_get_scf_progress returns log-derived progress when qdyn_scf.log exists."""
    (tmp_path / "qdyn_scf.log").write_text(
        "\n".join(
            [
                "Step: 3, Interval: 1",
                "Step     Global_idx     Category",
                "0        scf_001        normal",
                "1        scf_002        prehamgnn",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "scf_001").mkdir()
    (tmp_path / "scf_001" / "POSCAR").write_text("input", encoding="utf-8")

    running = tmp_path / "scf_002"
    running.mkdir()
    (running / "qdyn.scfout").write_text("running", encoding="utf-8")

    progress = _get_scf_progress(LocalRunDirAccess(tmp_path))

    assert progress.total_steps == 3
    assert progress.current_step == 1
    assert progress.batch is not None
    assert progress.batch.completed == 1
    assert progress.batch.running == 1
    assert progress.batch.pending == 1


def test_scf_progress_returns_unavailable_when_no_log(tmp_path: Path):
    """Without qdyn_scf.log, SCF progress is unavailable."""
    for name in ("scf_001", "scf_002"):
        d = tmp_path / name
        d.mkdir()
        (d / "POSCAR").write_text("input", encoding="utf-8")

    progress = _get_scf_progress(LocalRunDirAccess(tmp_path))

    assert progress.available is False
    assert progress.batch is None
    assert progress.current_frame is None


def test_scf_progress_product_files_without_log_are_unavailable(tmp_path: Path):
    """Product files do not make SCF progress available without qdyn_scf.log."""
    # No qdyn_scf.log at all
    d = tmp_path / "scf_001"
    d.mkdir()
    (d / "WAVECAR").write_text("wave", encoding="utf-8")
    (d / "wfc.npz").write_bytes(b"wfc")

    progress = _get_scf_progress(LocalRunDirAccess(tmp_path))

    assert progress.available is False
    assert progress.batch is None
