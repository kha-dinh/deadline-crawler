"""Tests for --year flag: comma-separated multi-year parsing (T15)."""

import pytest

from main import _parse_years


# --- Year parsing ---


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, None),
        ("2026", [2026]),
        ("2026,2027", [2026, 2027]),
        ("2025, 2026, 2027", [2025, 2026, 2027]),
    ],
)
def test_parse_years(raw, expected):
    assert _parse_years(raw) == expected


def test_parse_years_invalid():
    with pytest.raises(ValueError):
        _parse_years("abc")
