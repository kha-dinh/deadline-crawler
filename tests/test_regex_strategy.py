"""Tests for regex extraction strategy (T4)."""

import pytest
from unittest.mock import patch, MagicMock

from crawler.strategies.regex import RegexStrategy, _parse_deadline_date
from crawler.models import CrawlResult


# --- Date parsing (V2 format) ---


@pytest.mark.parametrize(
    "input_text, expected",
    [
        ("Tuesday, August 26, 2025, 11:59 pm AoE", "2025-08-26 23:59"),
        ("Thursday, February 5, 2026, 11:59 pm AoE", "2026-02-05 23:59"),
        ("Thursday, January 29, 2026, 11:59 pm AoE", "2026-01-29 23:59"),
        ("Tuesday, August 19, 2025, 11:59 pm AoE", "2025-08-19 23:59"),
        ("Thursday, February 5, 2026", "2026-02-05 00:00"),
        ("August 26, 2025", "2025-08-26 00:00"),
        ("nonsense text", None),
    ],
)
def test_parse_deadline_date(input_text, expected):
    assert _parse_deadline_date(input_text) == expected


# --- Strategy integration ---

SAMPLE_CFP_HTML = """
<h2>Important Dates</h2>
<h3 id="cycle1">Cycle 1</h3>
<ul>
    <li>Paper submissions (including artifacts) due: <strong>Tuesday, August 26, 2025, 11:59 pm AoE</strong></li>
</ul>
<h3 id="cycle2">Cycle 2</h3>
<ul>
    <li>Paper submissions due: <strong>Thursday, February 5, 2026, 11:59 pm AoE</strong></li>
</ul>
"""

SAMPLE_MAIN_HTML = """
<div class="field field-name-field-date-text">
    <div class="field-items"><div class="field-item odd">August 12\u201314, 2026</div></div>
</div>
<div class="field field-name-field-address-text">
    <div class="field-items"><div class="field-item odd">Baltimore, MD, USA</div></div>
</div>
"""

USENIX_CONF = {
    "name": "USENIX Security",
    "url": "https://www.usenix.org/conference/usenixsecurity{YY}/call-for-papers",
    "url_main": "https://www.usenix.org/conference/usenixsecurity{YY}",
    "strategy": "regex",
    "tags": ["SEC", "TIER1"],
    "cycles": [
        {
            "name": "Cycle 1",
            "selectors": {
                "deadline": r'id="cycle1".*?Paper submissions.*?due:\s*<strong>(.*?)</strong>',
            },
        },
        {
            "name": "Cycle 2",
            "selectors": {
                "deadline": r'id="cycle2".*?Paper submissions.*?due:\s*<strong>(.*?)</strong>',
            },
        },
    ],
    "main_selectors": {
        "date": ".field-name-field-date-text .field-item",
        "place": ".field-name-field-address-text .field-item",
    },
    "overrides": {
        "description": "USENIX Security Symposium",
    },
}


def _mock_get(url, **kwargs):
    resp = MagicMock()
    resp.text = SAMPLE_MAIN_HTML if "call-for-papers" not in url else SAMPLE_CFP_HTML
    return resp


@patch("crawler.strategies.regex.requests.get", side_effect=_mock_get)
def test_extract_usenix_cycles(mock_get):
    strategy = RegexStrategy()
    results = strategy.extract(USENIX_CONF, 2026)

    assert len(results) == 2

    c1, c2 = results
    assert c1.cycle == "Cycle 1"
    assert c1.deadlines == ["2025-08-26 23:59"]
    assert c2.cycle == "Cycle 2"
    assert c2.deadlines == ["2026-02-05 23:59"]

    # Both share main page fields
    for r in results:
        assert r.name == "USENIX Security"
        assert r.year == 2026
        assert r.date == "August 12\u201314, 2026"
        assert r.place == "Baltimore, MD, USA"
        assert r.description == "USENIX Security Symposium"
        assert r.tags == ["SEC", "TIER1"]


# --- No cycles (single-selector fallback) ---

SIMPLE_CONF = {
    "name": "SimpleConf",
    "url": "https://example.com/cfp",
    "strategy": "regex",
    "tags": ["GEN", "TIER2"],
    "selectors": {
        "deadline": r"Deadline:\s*<b>(.*?)</b>",
    },
}

SIMPLE_HTML = '<p>Deadline: <b>March 15, 2026</b></p>'


@patch("crawler.strategies.regex.requests.get")
def test_extract_no_cycles(mock_get):
    mock_get.return_value = MagicMock(text=SIMPLE_HTML)
    strategy = RegexStrategy()
    results = strategy.extract(SIMPLE_CONF, 2026)

    assert len(results) == 1
    assert results[0].cycle is None
    assert results[0].deadlines == ["2026-03-15 00:00"]


def test_extract_no_url():
    strategy = RegexStrategy()
    conf = {"name": "Bad", "url": None, "strategy": "regex", "tags": ["SEC"]}
    with pytest.raises(ValueError, match="no URL"):
        strategy.extract(conf, 2026)


@patch("crawler.strategies.regex.requests.get")
def test_extract_no_matches(mock_get):
    mock_get.return_value = MagicMock(text="<html>no deadlines here</html>")
    strategy = RegexStrategy()
    conf = {
        "name": "Empty",
        "url": "https://example.com",
        "strategy": "regex",
        "tags": ["SEC"],
        "selectors": {"deadline": r"will not match (.*)"},
    }
    results = strategy.extract(conf, 2026)
    assert len(results) == 1
    assert results[0].deadlines == []
