import pytest
from ase import Atoms

from qdyn.tools.nvt import check_nvt_convergence


def _structure() -> Atoms:
    return Atoms(
        "H4",
        positions=[
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 1.0],
            [0.0, 1.0, 0.0],
            [1.0, 0.0, 0.0],
        ],
    )


def _md_data(
    temperatures: list[float],
    potential_per_atom: list[float],
) -> dict:
    natoms = len(_structure())
    return {
        "temperatures": temperatures,
        "potential_energies": [
            potential_energy * natoms
            for potential_energy in potential_per_atom
        ],
        "time_ps": [float(i) for i in range(len(temperatures))],
    }


def test_check_nvt_convergence_passes_when_temperature_and_potential_plateau():
    md_data = _md_data(
        temperatures=[300.0, 300.5, 299.8, 300.1, 300.3, 299.9],
        potential_per_atom=[-2.0, -2.001, -1.999, -2.0, -2.002, -1.998],
    )

    converged, temp_avg, temp_std = check_nvt_convergence(
        _structure(),
        md_data,
        target_temp=300.0,
    )

    assert converged is True
    assert temp_avg == pytest.approx(300.1)
    assert temp_std == pytest.approx(0.23804761428476406)


def test_check_nvt_convergence_fails_when_potential_energy_trends_down():
    md_data = _md_data(
        temperatures=[300.0] * 10,
        potential_per_atom=[
            -2.00,
            -2.05,
            -2.10,
            -2.15,
            -2.20,
            -2.25,
            -2.30,
            -2.35,
            -2.40,
            -2.45,
        ],
    )

    converged, _, _ = check_nvt_convergence(
        _structure(),
        md_data,
        target_temp=300.0,
    )

    assert converged is False


def test_check_nvt_convergence_fails_when_potential_blocks_still_drift():
    md_data = _md_data(
        temperatures=[300.0] * 10,
        potential_per_atom=[
            -2.00,
            -2.00,
            -2.00,
            -2.00,
            -2.00,
            -2.03,
            -2.03,
            -2.03,
            -2.03,
            -2.03,
        ],
    )

    converged, _, _ = check_nvt_convergence(
        _structure(),
        md_data,
        target_temp=300.0,
    )

    assert converged is False


def test_check_nvt_convergence_requires_potential_energy_data():
    with pytest.raises(ValueError, match="No potential energy data"):
        check_nvt_convergence(
            _structure(),
            {"temperatures": [300.0] * 6},
            target_temp=300.0,
        )


def test_check_nvt_convergence_requires_time_ps_data():
    with pytest.raises(ValueError, match="No time_ps data"):
        check_nvt_convergence(
            _structure(),
            {
                "temperatures": [300.0] * 6,
                "potential_energies": [-8.0] * 6,
            },
            target_temp=300.0,
        )


def test_check_nvt_convergence_requires_time_ps_length_to_match():
    with pytest.raises(ValueError, match="Temperature and time_ps data lengths"):
        check_nvt_convergence(
            _structure(),
            {
                "temperatures": [300.0] * 6,
                "potential_energies": [-8.0] * 6,
                "time_ps": [0.0, 1.0, 2.0],
            },
            target_temp=300.0,
        )


def test_check_nvt_convergence_preserves_temperature_failure_behavior():
    md_data = _md_data(
        temperatures=[330.0] * 6,
        potential_per_atom=[-2.0] * 6,
    )

    converged, _, _ = check_nvt_convergence(
        _structure(),
        md_data,
        target_temp=300.0,
    )

    assert converged is False
