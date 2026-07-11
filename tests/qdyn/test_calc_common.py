from pathlib import Path
import re

import pytest
from ase import Atoms
from ase.constraints import FixAtoms
from ase.spacegroup import Spacegroup
from monty.json import jsanitize
import numpy as np
from qdyn.calc_common import parse_band_index
from qdyn.calc_common import stru_todict
from qdyn.calc_common import write_stru


class TestParseBandIndex:
    """parse_band_index: 1-based band index from symbolic expressions."""

    @pytest.mark.parametrize(
        "expr, vbm, nbands, expected",
        [
            ("VBM", 120, 200, 120),
            ("CBM", 120, 200, 121),
            ("HOMO", 120, 200, 120),
            ("LUMO", 120, 200, 121),
            ("VBM-3", 120, 200, 117),
            ("CBM+3", 120, 200, 124),
            ("HOMO-2", 120, 200, 118),
            ("LUMO+5", 120, 200, 126),
            ("50", 120, 200, 50),
            ("1", 120, 200, 1),
            # case insensitive
            ("vbm-3", 120, 200, 117),
            ("Vbm-3", 120, 200, 117),
            # leading/trailing whitespace
            (" VBM-3 ", 120, 200, 117),
            ("\tCBM+2\t", 120, 200, 123),
        ],
    )
    def test_valid_expressions(self, expr, vbm, nbands, expected):
        assert parse_band_index(expr, vbm, nbands) == expected

    @pytest.mark.parametrize(
        "expr, vbm, nbands, expected",
        [
            ("VBM-200", 120, 200, 1),
            ("CBM+200", 120, 200, 200),
            ("0", 120, 200, 1),
        ],
    )
    def test_clamp_to_valid_range(self, expr, vbm, nbands, expected):
        assert parse_band_index(expr, vbm, nbands) == expected

    @pytest.mark.parametrize("expr", ["10VBM", "VBM2", "abc", "VBM*2"])
    def test_rejects_invalid_expressions(self, expr):
        with pytest.raises((SyntaxError, ValueError)):
            parse_band_index(expr, 120, 200)


def test_write_stru_openmx_keeps_unique_species_order(tmp_path: Path, monkeypatch):
    from qdyn.params import ORBITAL_BASIS, PSEUDO_POTENTIAL, VALENCE_ELECTRONS
    monkeypatch.setitem(ORBITAL_BASIS, "Si", "Si7.0-s2p2d1")
    monkeypatch.setitem(ORBITAL_BASIS, "O", "O6.0-s2p2d1")
    monkeypatch.setitem(PSEUDO_POTENTIAL.setdefault('openmx', {}), "Si", "Si_PBE19")
    monkeypatch.setitem(PSEUDO_POTENTIAL.setdefault('openmx', {}), "O", "O_PBE19")
    monkeypatch.setitem(VALENCE_ELECTRONS.setdefault('openmx', {}), "Si", 4.0)
    monkeypatch.setitem(VALENCE_ELECTRONS.setdefault('openmx', {}), "O", 6.0)

    stru = Atoms(
        "SiOSi",
        positions=[
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 1.0],
            [0.0, 0.0, 2.0],
        ],
        cell=[5.0, 5.0, 5.0],
        pbc=True,
    )

    out_path = tmp_path / "qdyn.dat"
    write_stru(out_path, stru, "openmx-dat", extras="")

    text = out_path.read_text(encoding="utf-8")
    assert "Species.Number             2" in text
    assert "Atoms.Number                  3" in text
    species_block = re.search(
        r"<Atoms\.SpeciesAndCoordinates\s+(.*?)\s+Atoms\.SpeciesAndCoordinates>",
        text,
        re.S,
    )
    assert species_block is not None
    species_lines = species_block.group(1).strip().splitlines()
    assert len(species_lines) == 3
    assert [line.split()[1] for line in species_lines] == ["Si", "O", "Si"]


class TestStruTodict:
    """stru_todict: whitelist serialization safe for jobflow jsanitize."""

    def _make_cif_like_atoms(self) -> Atoms:
        """Build an Atoms object mimicking what ASE produces when reading a CIF.

        CIF readers store the crystallographic spacegroup in
        ``atoms.info["spacegroup"]`` as an ``ase.spacegroup.Spacegroup``
        instance, which lacks the ``as_dict`` method that monty's
        ``jsanitize(strict=True)`` relies on.
        """
        atoms = Atoms(
            "Si2",
            positions=[[0.0, 0.0, 0.0], [0.25, 0.25, 0.25]],
            cell=np.eye(3) * 5.43,
            pbc=True,
        )
        atoms.info["spacegroup"] = Spacegroup(227, setting=1)
        atoms.info["user_data"] = {"arbitrary": "stuff"}
        return atoms

    def test_strips_info_with_spacegroup(self):
        """stru_todict must not include the ``info`` key at all."""
        atoms = self._make_cif_like_atoms()
        d = stru_todict(atoms)
        assert "info" not in d

    def test_jsanitize_strict_passes(self):
        """The cleaned dict must survive ``jsanitize(strict=True)`` without
        raising ``AttributeError: 'Spacegroup' object has no attribute
        'as_dict'``."""
        atoms = self._make_cif_like_atoms()
        d = stru_todict(atoms)
        # Must not raise
        result = jsanitize(d, strict=True)
        assert "numbers" in result
        assert "positions" in result
        assert "cell" in result
        assert "pbc" in result

    def test_raw_todict_reproduces_bug(self):
        """Sanity check: the un-cleaned ``Atoms.todict()`` output *does*
        trigger the bug, confirming the test setup is meaningful."""
        atoms = self._make_cif_like_atoms()
        raw = atoms.todict()
        with pytest.raises(AttributeError, match="as_dict"):
            jsanitize(raw, strict=True)

    def test_whitelist_keys_only(self):
        """Only the whitelisted structural keys should be present."""
        atoms = self._make_cif_like_atoms()
        d = stru_todict(atoms)
        allowed = {"numbers", "positions", "cell", "pbc",
                   "momenta", "constraints"}
        assert set(d.keys()) <= allowed

    def test_roundtrip_fromdict(self):
        """``Atoms.fromdict`` must be able to reconstruct from the cleaned
        dict — i.e. dropping ``info`` does not break deserialization."""
        atoms = self._make_cif_like_atoms()
        d = stru_todict(atoms)
        restored = Atoms.fromdict(d)
        assert restored.get_chemical_formula() == "Si2"
        assert np.allclose(restored.positions, atoms.positions)

    def test_constraints_preserved(self):
        """FixAtoms constraints must survive the whitelist filtering and
        remain in the serialized ``todict()`` form."""
        atoms = self._make_cif_like_atoms()
        atoms.set_constraint(FixAtoms(indices=[0]))
        d = stru_todict(atoms)
        assert d.get("constraints") is not None
        assert len(d["constraints"]) == 1
        assert d["constraints"][0]["name"] == "FixAtoms"

    def test_momenta_preserved(self):
        """Momenta (NVE velocities) must be kept when present."""
        atoms = self._make_cif_like_atoms()
        atoms.set_velocities(np.zeros((2, 3)))
        d = stru_todict(atoms)
        assert "momenta" in d
