import pytest
from qdyn.calc_common import parse_band_index


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
