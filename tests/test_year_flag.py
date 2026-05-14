"""Tests for --year flag: comma-separated multi-year crawl (T15)."""

import pytest
from unittest.mock import patch, MagicMock

from main import _parse_years
from crawler.strategy import crawl_all


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


# --- Multi-year crawl dispatch ---


@patch("crawler.strategy.crawl_conference")
@patch("crawler.strategy.load_conferences")
@patch("crawler.strategy._ensure_strategies_loaded")
def test_crawl_all_multi_year(mock_ensure, mock_load, mock_crawl):
    """Each conference crawled once per year."""
    mock_load.return_value = [
        {"name": "ConfA", "strategy": "regex"},
    ]
    mock_crawl.return_value = [MagicMock()]

    results = crawl_all(years=[2026, 2027])

    assert mock_crawl.call_count == 2
    calls = mock_crawl.call_args_list
    assert calls[0].args == ({"name": "ConfA", "strategy": "regex"}, 2026)
    assert calls[1].args == ({"name": "ConfA", "strategy": "regex"}, 2027)
    assert len(results) == 2


@patch("crawler.strategy.crawl_conference")
@patch("crawler.strategy.load_conferences")
@patch("crawler.strategy._ensure_strategies_loaded")
def test_crawl_all_default_year(mock_ensure, mock_load, mock_crawl):
    """None years defaults to current year."""
    mock_load.return_value = [
        {"name": "ConfA", "strategy": "regex"},
    ]
    mock_crawl.return_value = []

    crawl_all(years=None)

    assert mock_crawl.call_count == 1
    year_arg = mock_crawl.call_args.args[1]
    import datetime
    assert year_arg == datetime.datetime.now().year
