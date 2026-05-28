"""Tests for qdyn.tools.pseuh — pseudo-hydrogen POSCAR/POTCAR handling."""

import pytest
from ase import Atoms
from ase.constraints import FixAtoms

from qdyn.tools.pseuh import (
    _charge_to_symbol,
    _symbol_to_charge,
    _charge_to_potcar_dir,
    _is_pseudo_h_symbol,
    _parse_pseudo_h_symbol,
    read_stru_pseuh,
    write_poscar_and_potcar,
)
from qdyn.calc_common import read_stru


# ---------------------------------------------------------------------------
# _charge_to_symbol
# ---------------------------------------------------------------------------

class TestChargeToSymbol:
    @pytest.mark.parametrize(
        "charge, expected",
        [
            (0.25, "H025"),
            (0.50, "H050"),
            (0.5, "H050"),
            (0.75, "H075"),
            (1.00, "H100"),
            (1.0, "H100"),
            (1.25, "H125"),
        ],
    )
    def test_valid_charges(self, charge, expected):
        assert _charge_to_symbol(charge) == expected

    def test_floating_point_robustness(self):
        assert _charge_to_symbol(0.1 + 0.4 + 0.25 + 0.25) == "H100"


# ---------------------------------------------------------------------------
# _symbol_to_charge
# ---------------------------------------------------------------------------

class TestSymbolToCharge:
    @pytest.mark.parametrize(
        "symbol, expected",
        [
            ("H025", 0.25),
            ("H050", 0.50),
            ("H075", 0.75),
            ("H100", 1.00),
            ("H125", 1.25),
        ],
    )
    def test_valid_symbols(self, symbol, expected):
        assert _symbol_to_charge(symbol) == expected

    def test_round_trip(self):
        for charge in (0.25, 0.5, 0.75, 1.0, 1.25):
            assert _symbol_to_charge(_charge_to_symbol(charge)) == charge


# ---------------------------------------------------------------------------
# _charge_to_potcar_dir
# ---------------------------------------------------------------------------

class TestChargeToPotcarDir:
    @pytest.mark.parametrize(
        "charge, expected",
        [
            (0.25, "H.25"),
            (0.50, "H.5"),
            (0.75, "H.75"),
            (1.0, "H"),
            (1.25, "H1.25"),
        ],
    )
    def test_valid_charges(self, charge, expected):
        assert _charge_to_potcar_dir(charge) == expected


# ---------------------------------------------------------------------------
# _is_pseudo_h_symbol
# ---------------------------------------------------------------------------

class TestIsPseudoHSymbol:
    @pytest.mark.parametrize(
        "symbol, expected",
        [
            ("H025", True),
            ("H050", True),
            ("H125", True),
            ("H5", False),
            ("H", False),
            ("H.5", False),
            ("He", False),
            ("Ga", False),
        ],
    )
    def test_detection(self, symbol, expected):
        assert _is_pseudo_h_symbol(symbol) is expected


# ---------------------------------------------------------------------------
# _parse_pseudo_h_symbol
# ---------------------------------------------------------------------------

class TestParsePseudoHSymbol:
    @pytest.mark.parametrize(
        "symbol, expected",
        [
            ("H.5", 0.5),
            ("H.75", 0.75),
            ("H.25", 0.25),
            ("H0.5", 0.5),
            ("H1.25", 1.25),
            ("H1", 1.0),
            ("H2", 2.0),
            ("H050", 0.5),
            ("H075", 0.75),
            ("H125", 1.25),
        ],
    )
    def test_parse_valid(self, symbol, expected):
        assert _parse_pseudo_h_symbol(symbol) == expected

    @pytest.mark.parametrize(
        "symbol",
        ["H", "He", "Ga", "X", ""],
    )
    def test_parse_invalid_returns_none(self, symbol):
        assert _parse_pseudo_h_symbol(symbol) is None


# ---------------------------------------------------------------------------
# read_poscar
# ---------------------------------------------------------------------------

class TestReadStruPseuh:
    def make_poscar_text(self, symbols_line, counts_line, coords_lines):
        header = (
            "Test system\n"
            "1.0\n"
            "    10.0  0.0  0.0\n"
            "    0.0  10.0  0.0\n"
            "    0.0   0.0 10.0\n"
        )
        return header + symbols_line + counts_line + "Cartesian\n" + coords_lines

    def test_plain_vasp_read(self, tmp_path):
        """Plain POSCAR without pseudo-H uses read_stru."""
        text = self.make_poscar_text(
            "Ga As\n", "1 1\n",
            "0.0 0.0 0.0\n2.0 0.0 0.0\n",
        )
        f = tmp_path / "POSCAR"
        f.write_text(text)
        atoms = read_stru(str(f))
        assert len(atoms) == 2
        assert atoms.get_chemical_symbols() == ["Ga", "As"]

    def test_pseudo_h1_poscar(self, tmp_path):
        text = self.make_poscar_text(
            "Si H100\n", "2 2\n",
            "0.0 0.0 0.0\n1.0 0.0 0.0\n0.0 1.0 0.0\n0.0 0.0 1.0\n",
        )
        f = tmp_path / "POSCAR"
        f.write_text(text)
        atoms = read_stru_pseuh(str(f))
        assert len(atoms) == 4
        symbols = atoms.get_chemical_symbols()
        assert symbols == ["Si", "Si", "H", "H"]
        tags = atoms.get_tags()
        assert tags[0] == 0  # Si
        assert tags[2] != 0  # pseudo-H

    def test_mixed_pseudo_h_poscar(self, tmp_path):
        text = self.make_poscar_text(
            "Ga As H050 H075\n", "1 1 1 1\n",
            "0.0 0.0 0.0\n1.0 0.0 0.0\n2.0 0.0 0.0\n3.0 0.0 0.0\n",
        )
        f = tmp_path / "POSCAR"
        f.write_text(text)
        atoms = read_stru_pseuh(str(f))
        assert len(atoms) == 4
        tags = atoms.get_tags()
        assert tags[2] != tags[3]

    def test_from_str_plain_poscar(self):
        """String-based POSCAR without pseudo-H uses read_stru."""
        text = self.make_poscar_text(
            "Ga As\n", "1 1\n",
            "0.0 0.0 0.0\n2.0 0.0 0.0\n",
        )
        atoms = read_stru(text, from_str=True)
        assert len(atoms) == 2
        assert atoms.get_chemical_symbols() == ["Ga", "As"]

    def test_from_str_with_pseudo_h(self):
        """String-based POSCAR with H050/H075 gets tags, sorted, and fixed."""
        text = self.make_poscar_text(
            "Si H050 H075\n", "2 1 1\n",
            "0.0 0.0 0.0\n1.0 0.0 0.0\n0.0 0.0 2.0\n0.0 0.0 3.0\n",
        )
        atoms = read_stru_pseuh(text, from_str=True)
        assert len(atoms) == 4
        tags = atoms.get_tags()
        # H050 → 50, H075 → 75, Si → 0; pseudo-H sorted to end
        assert list(tags) == [0, 0, 50, 75]
        # FixAtoms applied to pseudo-H
        assert len(atoms.constraints) > 0
        fixed = sorted(atoms.constraints[0].index)
        assert fixed == [2, 3]

    def test_read_stru_delegates_to_pseuh(self, tmp_path):
        """read_stru with pseudo_h=True delegates to read_stru_pseuh."""
        text = self.make_poscar_text(
            "Si H050\n", "2 1\n",
            "0.0 0.0 0.0\n1.0 0.0 0.0\n0.0 0.0 2.0\n",
        )
        f = tmp_path / "POSCAR"
        f.write_text(text)
        atoms = read_stru(str(f), pseudo_h=True)
        assert len(atoms) == 3
        tags = atoms.get_tags()
        assert list(tags) == [0, 0, 50]

    def test_unsupported_stru_format_raises(self):
        text = self.make_poscar_text(
            "Si H050\n", "2 1\n",
            "0.0 0.0 0.0\n1.0 0.0 0.0\n0.0 0.0 2.0\n",
        )
        with pytest.raises(ValueError, match="Unsupported stru_format"):
            read_stru_pseuh(text, stru_format='cp2k', from_str=True)


# ---------------------------------------------------------------------------
# write_poscar_and_potcar
# ---------------------------------------------------------------------------

def _make_tagged_atoms(symbols, tags, cell=None):
    """Build Atoms with explicit tags for pseudo-H testing."""
    atoms = Atoms(
        symbols,
        positions=[[0, 0, i] for i in range(len(symbols))],
        cell=cell or [10, 10, 10],
    )
    atoms.set_tags(tags)
    return atoms


class TestWritePoscarAndPotcar:
    def test_writes_poscar(self, tmp_path):
        atoms = Atoms(
            "GaAs", positions=[[0, 0, 0], [1, 0, 0]],
            cell=[10, 10, 10],
        )
        pp_path = tmp_path / "pp"
        for d in ("Ga_d", "As"):
            (pp_path / d).mkdir(parents=True)
            (pp_path / d / "POTCAR").write_text(f"{d}_potcar\n")

        write_poscar_and_potcar(
            atoms, pp_path=str(pp_path), output_dir=str(tmp_path),
        )
        assert (tmp_path / "POSCAR").is_file()

    def test_poscar_contains_placeholder_symbols(self, tmp_path):
        atoms = _make_tagged_atoms(["Si", "Si", "H"], [0, 0, 50])
        pp_path = tmp_path / "pp"
        for d in ("Si", "H.5"):
            (pp_path / d).mkdir(parents=True)
            (pp_path / d / "POTCAR").write_text(f"{d}_potcar\n")

        write_poscar_and_potcar(
            atoms, pp_path=str(pp_path), output_dir=str(tmp_path),
        )
        content = (tmp_path / "POSCAR").read_text()
        assert "H050" in content

    def test_potcar_concatenation(self, tmp_path):
        pp_path = tmp_path / "pp"
        (pp_path / "Ga_d").mkdir(parents=True)
        (pp_path / "Ga_d" / "POTCAR").write_text("Ga_potcar\n")
        (pp_path / "H.5").mkdir(parents=True)
        (pp_path / "H.5" / "POTCAR").write_text("H.5_potcar\n")

        atoms = _make_tagged_atoms(["Ga", "Ga", "H"], [0, 0, 50])
        write_poscar_and_potcar(
            atoms, pp_path=str(pp_path), output_dir=str(tmp_path),
        )
        potcar = (tmp_path / "POTCAR").read_text()
        assert "Ga_potcar" in potcar
        assert "H.5_potcar" in potcar

    def test_missing_potcar_raises(self, tmp_path):
        pp_path = tmp_path / "pp"
        (pp_path / "Ga_d").mkdir(parents=True)
        (pp_path / "Ga_d" / "POTCAR").write_text("Ga\n")

        atoms = _make_tagged_atoms(["Ga", "Ga", "H"], [0, 0, 50])
        with pytest.raises(FileNotFoundError, match="H050"):
            write_poscar_and_potcar(
                atoms, pp_path=str(pp_path), output_dir=str(tmp_path),
            )

    def test_pseudo_h_write_selective_dynamics(self, tmp_path):
        """Pseudo-H atoms are fixed → POSCAR has Selective Dynamics + F F F."""
        atoms = _make_tagged_atoms(["Si", "Si", "H"], [0, 0, 50])
        # Fix pseudo-H atoms
        atoms.set_constraint(FixAtoms(indices=[2]))

        pp_path = tmp_path / "pp"
        for d in ("Si", "H.5"):
            (pp_path / d).mkdir(parents=True)
            (pp_path / d / "POTCAR").write_text(f"{d}_potcar\n")

        write_poscar_and_potcar(
            atoms, pp_path=str(pp_path), output_dir=str(tmp_path),
        )
        content = (tmp_path / "POSCAR").read_text()
        assert "Selective dynamics" in content

    def test_constraints_merge_with_existing(self, tmp_path):
        """Existing FixAtoms are preserved alongside pseudo-H constraints."""
        atoms = _make_tagged_atoms(["Si", "Si", "H"], [0, 0, 50])
        atoms.set_constraint(FixAtoms(indices=[0, 2]))  # fix Si[0] and pseudo-H

        pp_path = tmp_path / "pp"
        for d in ("Si", "H.5"):
            (pp_path / d).mkdir(parents=True)
            (pp_path / d / "POTCAR").write_text(f"{d}_potcar\n")

        write_poscar_and_potcar(
            atoms, pp_path=str(pp_path), output_dir=str(tmp_path),
        )
        content = (tmp_path / "POSCAR").read_text()
        assert "Selective dynamics" in content
        # Read back and verify constraints via our reader
        atoms2 = read_stru_pseuh(str(tmp_path / "POSCAR"))
        assert len(atoms2.constraints) > 0
        fixed_indices = sorted(atoms2.constraints[0].index)  # type: ignore[union-attr]
        assert fixed_indices == [0, 2]

    def test_no_selective_dynamics_without_constraints(self, tmp_path):
        """No Selective Dynamics when there are no constraints."""
        atoms = Atoms(
            "GaAs", positions=[[0, 0, 0], [1, 0, 0]],
            cell=[10, 10, 10],
        )
        pp_path = tmp_path / "pp"
        for d in ("Ga_d", "As"):
            (pp_path / d).mkdir(parents=True)
            (pp_path / d / "POTCAR").write_text(f"{d}_potcar\n")

        write_poscar_and_potcar(
            atoms, pp_path=str(pp_path), output_dir=str(tmp_path),
        )
        content = (tmp_path / "POSCAR").read_text()
        assert "Selective dynamics" not in content

    def test_custom_pseudo_map(self, tmp_path):
        pp_path = tmp_path / "pp"
        (pp_path / "H.5_GW").mkdir(parents=True)
        (pp_path / "H.5_GW" / "POTCAR").write_text("H.5_GW_potcar\n")

        atoms = _make_tagged_atoms(["H"], [50])
        write_poscar_and_potcar(
            atoms, pp_path=str(pp_path), output_dir=str(tmp_path),
            pseudo_map={"H050": "H.5_GW"},
        )
        potcar = (tmp_path / "POTCAR").read_text()
        assert "H.5_GW_potcar" in potcar

    def test_custom_potcar_map(self, tmp_path):
        pp_path = tmp_path / "pp"
        (pp_path / "Ga_custom").mkdir(parents=True)
        (pp_path / "Ga_custom" / "POTCAR").write_text("Ga_custom\n")

        atoms = Atoms("Ga", positions=[[0, 0, 0]], cell=[10, 10, 10])
        write_poscar_and_potcar(
            atoms, pp_path=str(pp_path), output_dir=str(tmp_path),
            potcar_map={"Ga": "Ga_custom"},
        )
        potcar = (tmp_path / "POTCAR").read_text()
        assert "Ga_custom" in potcar


# ---------------------------------------------------------------------------
# read_stru_pseuh strict validation
# ---------------------------------------------------------------------------

class TestReadStruPseuhStrict:
    def make_poscar_text(self, symbols_line, counts_line, coords_lines):
        header = (
            "Test system\n"
            "1.0\n"
            "    10.0  0.0  0.0\n"
            "    0.0  10.0  0.0\n"
            "    0.0   0.0 10.0\n"
        )
        return header + symbols_line + counts_line + "Cartesian\n" + coords_lines

    def test_rejects_h_dot_format(self, tmp_path):
        poscar_text = self.make_poscar_text(
            "Si H.5\n", "2 1\n",
            "0.0 0.0 0.0\n1.0 0.0 0.0\n0.0 0.0 2.0\n",
        )
        f = tmp_path / "POSCAR"
        f.write_text(poscar_text)
        with pytest.raises(ValueError, match="H.5"):
            read_stru_pseuh(str(f))

    def test_rejects_h1_format(self, tmp_path):
        poscar_text = self.make_poscar_text(
            "Si H1\n", "2 1\n",
            "0.0 0.0 0.0\n1.0 0.0 0.0\n0.0 0.0 2.0\n",
        )
        f = tmp_path / "POSCAR"
        f.write_text(poscar_text)
        with pytest.raises(ValueError, match="H1"):
            read_stru_pseuh(str(f))

    def test_rejects_invalid_charge(self, tmp_path):
        poscar_text = self.make_poscar_text(
            "Si H999\n", "2 1\n",
            "0.0 0.0 0.0\n1.0 0.0 0.0\n0.0 0.0 2.0\n",
        )
        f = tmp_path / "POSCAR"
        f.write_text(poscar_text)
        with pytest.raises(ValueError, match="H999"):
            read_stru_pseuh(str(f))

    def test_rejects_no_pseudo_h_when_required(self, tmp_path):
        poscar_text = self.make_poscar_text(
            "Ga As\n", "1 1\n",
            "0.0 0.0 0.0\n1.0 0.0 0.0\n",
        )
        f = tmp_path / "POSCAR"
        f.write_text(poscar_text)
        with pytest.raises(ValueError, match="No pseudo-hydrogen"):
            read_stru_pseuh(str(f))

    def test_accepts_valid_h050_format(self, tmp_path):
        poscar_text = self.make_poscar_text(
            "Si H050 H075\n", "2 1 1\n",
            "0.0 0.0 0.0\n1.0 0.0 0.0\n0.0 0.0 2.0\n0.0 0.0 3.0\n",
        )
        f = tmp_path / "POSCAR"
        f.write_text(poscar_text)
        atoms = read_stru_pseuh(str(f))
        assert len(atoms) == 4
        tags = atoms.get_tags()
        # H050 → tag 50, H075 → tag 75, Si → tag 0
        assert 50 in tags
        assert 75 in tags

    def test_from_str_rejects_bad_format(self):
        poscar_text = self.make_poscar_text(
            "Si H.5\n", "2 1\n",
            "0.0 0.0 0.0\n1.0 0.0 0.0\n0.0 0.0 2.0\n",
        )
        with pytest.raises(ValueError, match="H.5"):
            read_stru_pseuh(poscar_text, from_str=True)

