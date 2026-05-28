"""Tests for pseudo-H integration in the NVT workflow.

Validates the end-to-end data flow: POSCAR (pseudo-H) → read_stru_pseuh →
todict() → Atoms.fromdict() → write_poscar_and_potcar → CONTCAR readback.
"""

import pytest
from ase import Atoms
from ase.constraints import FixAtoms

from qdyn.tools.pseuh import (
    read_stru_pseuh,
    write_poscar_and_potcar,
    _charge_to_symbol,
)
from qdyn.calc_common import read_stru


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_poscar_text(symbols_line, counts_line, coords_lines):
    header = (
        "Test system\n"
        "1.0\n"
        "    10.0  0.0  0.0\n"
        "    0.0  10.0  0.0\n"
        "    0.0   0.0 10.0\n"
    )
    return header + symbols_line + counts_line + "Cartesian\n" + coords_lines


# ---------------------------------------------------------------------------
# Test 1: tags survive dict roundtrip
# ---------------------------------------------------------------------------

class TestTagsSurviveDictRoundtrip:
    def test_tags_preserved(self):
        """Atoms.todict() → Atoms.fromdict() preserves ASE tags.

        Constraints must be manually serialised via .todict() on each
        constraint, matching the real NVT flow in qdyn_nvt.
        """
        atoms = Atoms(
            "SiSiHH",
            positions=[[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
            cell=[10, 10, 10],
        )
        atoms.set_tags([0, 0, 50, 75])
        atoms.set_constraint(FixAtoms(indices=[2, 3]))

        d = atoms.todict()
        if d.get('constraints') is not None:
            d['constraints'] = [c.todict() for c in d['constraints']]
        restored = Atoms.fromdict(d)

        assert list(restored.get_tags()) == [0, 0, 50, 75]
        assert len(restored.constraints) == 1
        assert sorted(restored.constraints[0].index) == [2, 3]  # type: ignore[union-attr]

    def test_no_tags_survives(self):
        """Roundtrip works for structures without tags."""
        atoms = Atoms(
            "GaAs",
            positions=[[0, 0, 0], [1, 0, 0]],
            cell=[10, 10, 10],
        )
        d = atoms.todict()
        restored = Atoms.fromdict(d)
        assert list(restored.get_tags()) == [0, 0]
        assert not restored.constraints


# ---------------------------------------------------------------------------
# Test 2: write POSCAR + POTCAR from dict-restored atoms
# ---------------------------------------------------------------------------

class TestWritePoscarWithPseudoHFromDict:
    def test_poscar_has_placeholder_symbols(self, tmp_path):
        """After dict roundtrip, POSCAR still contains H050."""
        # Simulate: read_stru_pseuh → todict → fromdict
        text = _make_poscar_text(
            "Si H050\n", "2 1\n",
            "0.0 0.0 0.0\n1.0 0.0 0.0\n0.0 0.0 2.0\n",
        )
        atoms = read_stru_pseuh(text, from_str=True)
        d = atoms.todict()
        if d.get('constraints') is not None:
            d['constraints'] = [c.todict() for c in d['constraints']]
        atoms2 = Atoms.fromdict(d)

        pp_path = tmp_path / "pp"
        for d in ("Si", "H.5"):
            (pp_path / d).mkdir(parents=True)
            (pp_path / d / "POTCAR").write_text(f"{d}_potcar\n")

        write_poscar_and_potcar(
            atoms2, pp_path=str(pp_path), output_dir=str(tmp_path),
        )
        content = (tmp_path / "POSCAR").read_text()
        assert "H050" in content

    def test_potcar_has_pseudo_h(self, tmp_path):
        """POTCAR includes pseudo-H pseudopotential."""
        pp_path = tmp_path / "pp"
        (pp_path / "Si").mkdir(parents=True)
        (pp_path / "Si" / "POTCAR").write_text("Si_potcar\n")
        (pp_path / "H.5").mkdir(parents=True)
        (pp_path / "H.5" / "POTCAR").write_text("H.5_potcar\n")

        atoms = Atoms(
            "SiSiH",
            positions=[[0, 0, 0], [1, 0, 0], [0, 0, 2]],
            cell=[10, 10, 10],
        )
        atoms.set_tags([0, 0, 50])

        write_poscar_and_potcar(
            atoms, pp_path=str(pp_path), output_dir=str(tmp_path),
        )
        potcar = (tmp_path / "POTCAR").read_text()
        assert "Si_potcar" in potcar
        assert "H.5_potcar" in potcar

    def test_selective_dynamics_for_pseudo_h(self, tmp_path):
        """Pseudo-H atoms are written with F F F flags."""
        text = _make_poscar_text(
            "Si H050\n", "2 1\n",
            "0.0 0.0 0.0\n1.0 0.0 0.0\n0.0 0.0 2.0\n",
        )
        atoms = read_stru_pseuh(text, from_str=True)

        pp_path = tmp_path / "pp"
        for d in ("Si", "H.5"):
            (pp_path / d).mkdir(parents=True)
            (pp_path / d / "POTCAR").write_text(f"{d}_potcar\n")

        write_poscar_and_potcar(
            atoms, pp_path=str(pp_path), output_dir=str(tmp_path),
        )
        content = (tmp_path / "POSCAR").read_text()
        assert "Selective dynamics" in content
        # The last coordinate line (pseudo-H) should be fixed: "F   F   F"
        last_coord_line = content.strip().split('\n')[-1]
        assert last_coord_line.count('F') == 3


# ---------------------------------------------------------------------------
# Test 3: CONTCAR readback with pseudo-H
# ---------------------------------------------------------------------------

class TestContcarReadback:
    def test_read_stru_with_pseudo_h_reads_contcar(self, tmp_path):
        """read_stru(pseudo_h=True) reads VASP output with placeholder symbols."""
        text = _make_poscar_text(
            "Si H050 H075\n", "2 1 1\n",
            "0.0 0.0 0.0\n1.0 0.0 0.0\n0.0 0.0 2.0\n0.0 0.0 3.0\n",
        )
        f = tmp_path / "POSCAR"
        f.write_text(text)

        atoms = read_stru(str(f), pseudo_h=True)
        assert len(atoms) == 4
        tags = atoms.get_tags()
        assert 50 in tags
        assert 75 in tags
        # FixAtoms applied to pseudo-H (sorted to end)
        assert len(atoms.constraints) > 0
        fixed = sorted(atoms.constraints[0].index)  # type: ignore[union-attr]
        assert len(fixed) == 2

    def test_roundtrip_poscar_contcar(self, tmp_path):
        """Write POSCAR with pseudo-H, read back with read_stru(pseudo_h=True)."""
        text = _make_poscar_text(
            "Si H050 H075\n", "2 1 2\n",
            "0.0 0.0 0.0\n1.0 0.0 0.0\n"
            "0.0 0.0 2.0\n0.0 0.0 3.0\n0.0 0.0 4.0\n",
        )
        atoms = read_stru_pseuh(text, from_str=True)

        pp_path = tmp_path / "pp"
        for d in ("Si", "H.5", "H.75"):
            (pp_path / d).mkdir(parents=True)
            (pp_path / d / "POTCAR").write_text(f"{d}_potcar\n")

        write_poscar_and_potcar(
            atoms, pp_path=str(pp_path), output_dir=str(tmp_path),
        )

        # simulate VASP CONTCAR readback
        atoms2 = read_stru(str(tmp_path / "POSCAR"), pseudo_h=True)
        assert len(atoms2) == len(atoms)
        assert 50 in atoms2.get_tags()
        assert 75 in atoms2.get_tags()
        # both pseudo-H types get FixAtoms
        pseudo_tags = [t for t in atoms2.get_tags() if t > 0]
        assert len(pseudo_tags) == 3


# ---------------------------------------------------------------------------
# Test 4: pseudo_h=False is a noop
# ---------------------------------------------------------------------------

class TestPseudoHInactive:
    def test_read_stru_plain(self, tmp_path):
        """read_stru(pseudo_h=False) is equivalent to ase.io.read."""
        text = _make_poscar_text(
            "Ga As\n", "1 1\n",
            "0.0 0.0 0.0\n2.0 0.0 0.0\n",
        )
        f = tmp_path / "POSCAR"
        f.write_text(text)
        atoms = read_stru(str(f), pseudo_h=False)
        assert atoms.get_chemical_symbols() == ["Ga", "As"]

    def test_read_stru_with_pseudo_h_symbols_no_flag_fails(self, tmp_path):
        """read_stru(pseudo_h=False) on a POSCAR with H050 should use ase.io.read
        which doesn't know about H050."""
        text = _make_poscar_text(
            "Si H050\n", "2 1\n",
            "0.0 0.0 0.0\n1.0 0.0 0.0\n0.0 0.0 2.0\n",
        )
        f = tmp_path / "POSCAR"
        f.write_text(text)
        with pytest.raises(Exception):
            read_stru(str(f), pseudo_h=False)
