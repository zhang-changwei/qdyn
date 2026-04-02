from datetime import datetime, timezone

from qdyn.frontend_api.service import _dt_str


def test_dt_str_marks_naive_datetime_as_utc():
    assert _dt_str(datetime(2026, 4, 2, 12, 28, 9)) == "2026-04-02T12:28:09Z"


def test_dt_str_preserves_explicit_timezone():
    assert _dt_str(datetime(2026, 4, 2, 20, 28, 9, tzinfo=timezone.utc)) == "2026-04-02T20:28:09Z"


def test_dt_str_adds_utc_suffix_to_naive_iso_string():
    assert _dt_str("2026-04-02T12:28:09") == "2026-04-02T12:28:09Z"
