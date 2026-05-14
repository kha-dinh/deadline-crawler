"""Tests for regex extraction strategy (T4, T16)."""

import pytest
from unittest.mock import patch, MagicMock

from crawler.strategies.regex import (
    RegexStrategy, _parse_deadline_date,
    _extract_deadlines_generic, _match_label, _strip_html,
    LABEL_MAP,
)
from crawler.models import CrawlResult


# --- Date parsing (V2 format) ---


@pytest.mark.parametrize(
    "input_text, expected",
    [
        # Full day-of-week + full month + time + tz
        ("Tuesday, August 26, 2025, 11:59 pm AoE", "2025-08-26 23:59"),
        ("Thursday, February 5, 2026, 11:59 pm AoE", "2026-02-05 23:59"),
        ("Thursday, January 29, 2026, 11:59 pm AoE", "2026-01-29 23:59"),
        ("Tuesday, August 19, 2025, 11:59 pm AoE", "2025-08-19 23:59"),
        # Full day-of-week + full month, no time
        ("Thursday, February 5, 2026", "2026-02-05 23:59"),
        # Full month, no day-of-week
        ("August 26, 2025", "2025-08-26 23:59"),
        # Short month (S&P style): "June 5, 2025"
        ("June 5, 2025", "2025-06-05 23:59"),
        ("May 29, 2025", "2025-05-29 23:59"),
        ("November 13, 2025", "2025-11-13 23:59"),
        # S&P with trailing "mandatory"
        ("May 29, 2025 mandatory", "2025-05-29 23:59"),
        # Short day-of-week + "DD Month YYYY" (NDSS style)
        ("Wed, 23 April 2025", "2025-04-23 23:59"),
        ("Wed, 6 August 2025", "2025-08-06 23:59"),
        # CCS style: "Jan 7, 2026"
        ("Jan 7, 2026", "2026-01-07 23:59"),
        ("Jan 14, 2026", "2026-01-14 23:59"),
        ("Apr 22, 2026", "2026-04-22 23:59"),
        ("Apr 29, 2026", "2026-04-29 23:59"),
        # Semicolon time format (SOSP style)
        ("April 10, 2025; 23:59 PT", "2025-04-10 23:59"),
        ("April 17, 2025; 23:59 PT", "2025-04-17 23:59"),
        # Parenthetical suffix (EuroSys/ASPLOS style)
        ("Tuesday May 14, 2024 (AoE)", "2024-05-14 23:59"),
        ("March 05, 2025 (11:59pm Eastern)", "2025-03-05 23:59"),
        # &nbsp; entity (ASPLOS summer cycle)
        ("Aug 13,&nbsp; 2025", "2025-08-13 23:59"),
        # US timezone prefix (NSDI style)
        ("Friday, April 18, 2025, 11:59 pm US PDT", "2025-04-18 23:59"),
        # Day-of-week without comma (EuroSys style)
        ("Tuesday May 14, 2024", "2024-05-14 23:59"),
        # Garbage
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
<h3>Submission Deadlines</h3>
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
                "section": r'id="cycle1".*?(?=id="cycle2"|<h3.*Submission Deadlines)',
                "deadlines": [
                    {"label": "submission", "pattern": r'Paper submissions.*?due:\s*<strong>(.*?)</strong>'},
                ],
            },
        },
        {
            "name": "Cycle 2",
            "selectors": {
                "section": r'id="cycle2".*?(?=<h3.*Submission Deadlines|<h2|$)',
                "deadlines": [
                    {"label": "submission", "pattern": r'Paper submissions due:\s*<strong>(.*?)</strong>'},
                ],
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
    assert c1.deadlines == [{"label": "submission", "date": "2025-08-26 23:59"}]
    assert c2.cycle == "Cycle 2"
    assert c2.deadlines == [{"label": "submission", "date": "2026-02-05 23:59"}]

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
        "deadlines": [
            {"label": "submission", "pattern": r"Deadline:\s*<b>(.*?)</b>"},
        ],
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
    assert results[0].deadlines == [{"label": "submission", "date": "2026-03-15 23:59"}]


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
        "selectors": {"deadlines": [{"label": "submission", "pattern": r"will not match (.*)"}]},
    }
    results = strategy.extract(conf, 2026)
    assert len(results) == 1
    assert results[0].deadlines == []


# --- Section-scoped extraction (S&P / CCS / NDSS style) ---

SP_HTML = """
<h2 id="important-dates"><strong>Important Dates</strong></h2>
<p>All deadlines are 23:59:59 AoE (UTC-12).</p>

<h4 id="first-deadline"><strong>First deadline</strong></h4>
<ul>
  <li>Abstract registration deadline: May 29, 2025 mandatory</li>
  <li>Paper submission deadline: June 5, 2025</li>
  <li>Early-reject notification: July 21, 2025</li>
  <li>Camera-ready deadline: October 17, 2025</li>
</ul>

<h4 id="second-deadline"><strong>Second deadline</strong></h4>
<ul>
  <li>Abstract, author, and conflict-of-interest registration deadline: November 6, 2025, mandatory (This means full and complete abstract.)</li>
  <li>Paper submission deadline: November 13, 2025</li>
  <li>Early-reject notification: January 19, 2026</li>
  <li>Camera-ready deadline: April 17, 2026</li>
</ul>
"""

SP_CONF = {
    "name": "S&P",
    "url": "https://sp{YYYY}.ieee-security.org/cfpapers.html",
    "strategy": "regex",
    "tags": ["SEC", "TIER1"],
    "cycles": [
        {
            "name": "Cycle 1",
            "selectors": {
                "section": 'id="first-deadline".*?</ul>',
                "deadlines": [
                    {"label": "abstract", "pattern": r"<li>Abstract registration deadline:\s*(.*?)(?:\s+mandatory)?</li>"},
                    {"label": "submission", "pattern": r"<li>Paper submission deadline:\s*(.*?)</li>"},
                ],
            },
        },
        {
            "name": "Cycle 2",
            "selectors": {
                "section": 'id="second-deadline".*?</ul>',
                "deadlines": [
                    {"label": "abstract", "pattern": r"<li>Abstract.*?registration deadline:\s*(.*?)(?:,\s*mandatory)?(?:\s*\(.*?\))?</li>"},
                    {"label": "submission", "pattern": r"<li>Paper submission deadline:\s*(.*?)</li>"},
                ],
            },
        },
    ],
    "overrides": {"description": "IEEE Symposium on Security and Privacy"},
}


@patch("crawler.strategies.regex.requests.get")
def test_extract_sp_cycles_with_section(mock_get):
    mock_get.return_value = MagicMock(text=SP_HTML)
    strategy = RegexStrategy()
    results = strategy.extract(SP_CONF, 2026)

    assert len(results) == 2
    c1, c2 = results

    assert c1.cycle == "Cycle 1"
    c1_dates = {d["date"] for d in c1.deadlines}
    assert "2025-05-29 23:59" in c1_dates
    assert "2025-06-05 23:59" in c1_dates
    assert {"label": "abstract", "date": "2025-05-29 23:59"} in c1.deadlines
    assert {"label": "submission", "date": "2025-06-05 23:59"} in c1.deadlines

    assert c2.cycle == "Cycle 2"
    c2_dates = {d["date"] for d in c2.deadlines}
    assert "2025-11-06 23:59" in c2_dates
    assert "2025-11-13 23:59" in c2_dates
    assert {"label": "abstract", "date": "2025-11-06 23:59"} in c2.deadlines
    assert {"label": "submission", "date": "2025-11-13 23:59"} in c2.deadlines

    # No cross-contamination between cycles
    for dl in c1.deadlines:
        assert dl["date"].startswith("2025-05") or dl["date"].startswith("2025-06")
    for dl in c2.deadlines:
        assert dl["date"].startswith("2025-11")


CCS_HTML = """
<h3 id="first-review-cycle">First Review Cycle</h3>
<ul>
  <li><strong>Abstract submission deadline</strong><br>Jan 7, 2026 <em>(Mandatory)</em></li>
  <li><strong>Full paper submission deadline</strong><br>Jan 14, 2026</li>
  <li><strong>Author notification</strong><br>Apr 9, 2026</li>
</ul>

<h3 id="second-review-cycle">Second Review Cycle</h3>
<ul>
  <li><strong>Abstract submission deadline</strong><br>Apr 22, 2026 <em>(Mandatory)</em></li>
  <li><strong>Full paper submission deadline</strong><br>Apr 29, 2026</li>
  <li><strong>Author notification</strong><br>July 17, 2026</li>
</ul>
"""

CCS_CONF = {
    "name": "CCS",
    "url": "https://www.sigsac.org/ccs/CCS{YYYY}/call-for/call-for-papers.html",
    "strategy": "regex",
    "tags": ["SEC", "TIER1"],
    "cycles": [
        {
            "name": "Cycle A",
            "selectors": {
                "section": 'id="first-review-cycle".*?</ul>',
                "deadlines": [
                    {"label": "abstract", "pattern": r"<li><strong>Abstract submission deadline</strong><br>\s*(.*?)(?:\s*<em>.*?)?</li>"},
                    {"label": "submission", "pattern": r"<li><strong>Full paper submission deadline</strong><br>\s*(.*?)(?:\s*<em>.*?)?</li>"},
                ],
            },
        },
        {
            "name": "Cycle B",
            "selectors": {
                "section": 'id="second-review-cycle".*?</ul>',
                "deadlines": [
                    {"label": "abstract", "pattern": r"<li><strong>Abstract submission deadline</strong><br>\s*(.*?)(?:\s*<em>.*?)?</li>"},
                    {"label": "submission", "pattern": r"<li><strong>Full paper submission deadline</strong><br>\s*(.*?)(?:\s*<em>.*?)?</li>"},
                ],
            },
        },
    ],
    "overrides": {"description": "ACM Conference on Computer and Communications Security"},
}


@patch("crawler.strategies.regex.requests.get")
def test_extract_ccs_cycles_with_section(mock_get):
    mock_get.return_value = MagicMock(text=CCS_HTML)
    strategy = RegexStrategy()
    results = strategy.extract(CCS_CONF, 2026)

    assert len(results) == 2
    ca, cb = results

    assert ca.cycle == "Cycle A"
    assert {"label": "abstract", "date": "2026-01-07 23:59"} in ca.deadlines
    assert {"label": "submission", "date": "2026-01-14 23:59"} in ca.deadlines

    assert cb.cycle == "Cycle B"
    assert {"label": "abstract", "date": "2026-04-22 23:59"} in cb.deadlines
    assert {"label": "submission", "date": "2026-04-29 23:59"} in cb.deadlines


NDSS_HTML = """
<h3 class="wp-block-heading">Summer Cycle</h3>
<ul>
<li>Wed, 23 April 2025: Paper submission deadline</li>
<li>Wed, 28 May 2025: Early reject/Round 2 notification and Round 1 reviews</li>
<li>Wed, 2 July 2025: Author notification</li>
<li>Wed, 10 September 2025: Camera Ready deadline</li>
</ul>

<h3 class="wp-block-heading">Fall Cycle</h3>
<ul>
<li>Wed, 6 August 2025: Paper submission deadline</li>
<li>Wed, 17 September 2025: Early reject/Round 2 notification and Round 1 reviews</li>
<li>Wed, 22 October 2025: Author notification</li>
<li>Wed, 17 December 2025: Camera Ready deadline</li>
</ul>
<h3>Something else</h3>
"""

NDSS_CONF = {
    "name": "NDSS",
    "url": "https://www.ndss-symposium.org/ndss{YYYY}/submissions/call-for-papers/",
    "strategy": "regex",
    "tags": ["SEC", "TIER1"],
    "cycles": [
        {
            "name": "Summer",
            "selectors": {
                "section": r"Summer Cycle</h3>.*?(?=Fall Cycle</h3>|<h3)",
                "deadlines": [
                    {"label": "submission", "pattern": r"<li>\w+,\s*([^<:]+):\s*Paper submission deadline"},
                    {"label": "early_reject", "pattern": r"<li>\w+,\s*([^<:]+):\s*Early reject"},
                    {"label": "notification", "pattern": r"<li>\w+,\s*([^<:]+):\s*Author notification<"},
                    {"label": "camera_ready", "pattern": r"<li>\w+,\s*([^<:]+):\s*Camera Ready deadline"},
                ],
            },
        },
        {
            "name": "Fall",
            "selectors": {
                "section": r"Fall Cycle</h3>.*?(?=<h2|<h3|$)",
                "deadlines": [
                    {"label": "submission", "pattern": r"<li>\w+,\s*([^<:]+):\s*Paper submission deadline"},
                    {"label": "early_reject", "pattern": r"<li>\w+,\s*([^<:]+):\s*Early reject"},
                    {"label": "notification", "pattern": r"<li>\w+,\s*([^<:]+):\s*Author notification<"},
                    {"label": "camera_ready", "pattern": r"<li>\w+,\s*([^<:]+):\s*Camera Ready deadline"},
                ],
            },
        },
    ],
    "overrides": {"description": "ISOC Network and Distributed System Security Symposium"},
}


@patch("crawler.strategies.regex.requests.get")
def test_extract_ndss_cycles_with_section(mock_get):
    mock_get.return_value = MagicMock(text=NDSS_HTML)
    strategy = RegexStrategy()
    results = strategy.extract(NDSS_CONF, 2026)

    assert len(results) == 2
    summer, fall = results

    assert summer.cycle == "Summer"
    assert {"label": "submission", "date": "2025-04-23 23:59"} in summer.deadlines
    assert {"label": "early_reject", "date": "2025-05-28 23:59"} in summer.deadlines
    assert {"label": "notification", "date": "2025-07-02 23:59"} in summer.deadlines
    assert {"label": "camera_ready", "date": "2025-09-10 23:59"} in summer.deadlines

    assert fall.cycle == "Fall"
    assert {"label": "submission", "date": "2025-08-06 23:59"} in fall.deadlines
    assert {"label": "early_reject", "date": "2025-09-17 23:59"} in fall.deadlines
    assert {"label": "notification", "date": "2025-10-22 23:59"} in fall.deadlines
    assert {"label": "camera_ready", "date": "2025-12-17 23:59"} in fall.deadlines


# --- T16: Generic text extractor ---


def test_label_map_covers_all_v10():
    """V11: label map must cover all V10 canonical labels."""
    v10_labels = {
        "abstract", "submission", "early_reject", "rebuttal_start",
        "rebuttal_end", "notification", "shepherd", "camera_ready",
    }
    assert set(LABEL_MAP.keys()) == v10_labels
    # Each label must have at least one phrase
    for label, phrases in LABEL_MAP.items():
        assert len(phrases) >= 1, f"{label} has no phrases"


def test_match_label_basics():
    assert _match_label("Abstract registration deadline") == "abstract"
    assert _match_label("Paper submission deadline") == "submission"
    assert _match_label("Author notification") == "notification"
    assert _match_label("Camera-ready deadline") == "camera_ready"
    assert _match_label("Early reject notification") == "early_reject"
    assert _match_label("something unrelated") is None


def test_strip_html():
    html = '<li><strong>Submission deadline</strong>: <b>June 10, 2026</b></li>'
    text = _strip_html(html)
    assert "<" not in text
    assert "Submission deadline" in text
    assert "June 10, 2026" in text


def test_generic_extractor_li_format():
    """Generic extractor handles <li> date lists (common format)."""
    html = """
    <h2>Important Dates</h2>
    <ul>
      <li>Abstract registration deadline: May 29, 2025</li>
      <li>Paper submission deadline: June 5, 2025</li>
      <li>Author notification: September 9, 2025</li>
      <li>Camera-ready deadline: October 17, 2025</li>
    </ul>
    """
    deadlines = _extract_deadlines_generic(html)
    labels = {d["label"] for d in deadlines}
    assert "abstract" in labels
    assert "submission" in labels
    assert "notification" in labels
    assert "camera_ready" in labels
    assert {"label": "submission", "date": "2025-06-05 23:59"} in deadlines


def test_generic_extractor_table_format():
    """Generic extractor handles <td> table rows (SOSP/ATC style)."""
    html = """
    <table>
      <tr><td>Deadline to register abstracts</td><td>March 26, 2026</td></tr>
      <tr><td><b>Submission deadline</b></td><td>April 1, 2026</td></tr>
      <tr><td>Author notification</td><td>July 3, 2026</td></tr>
      <tr><td><b>Camera ready due</b></td><td>August 28, 2026</td></tr>
    </table>
    """
    deadlines = _extract_deadlines_generic(html)
    labels = {d["label"] for d in deadlines}
    assert "abstract" in labels
    assert "submission" in labels
    assert "notification" in labels
    assert "camera_ready" in labels


def test_generic_extractor_eurosys_format():
    """Generic extractor handles EuroSys plain-text list items."""
    html = """
    <h3>Spring deadline</h3>
    <p>
      <li>Paper titles and abstracts due: Thursday, May 8, 2025 (AoE)</li>
      <li>Full paper submissions due: Thursday, May 15, 2025 (AoE)</li>
      <li>Notification to authors: Friday, August 22, 2025 (AoE)</li>
      <li>Camera-ready deadline: Friday, September 26, 2025 (AoE)</li>
    </p>
    """
    deadlines = _extract_deadlines_generic(html)
    labels = {d["label"] for d in deadlines}
    assert "abstract" in labels
    assert "submission" in labels
    assert "notification" in labels
    assert "camera_ready" in labels
    assert {"label": "abstract", "date": "2025-05-08 23:59"} in deadlines


def test_generic_extractor_reverse_format():
    """Generic extractor handles date-before-label (NDSS style)."""
    html = """
    <ul>
      <li>Wed, 23 April 2025: Paper submission deadline</li>
      <li>Wed, 28 May 2025: Early reject notification</li>
      <li>Wed, 2 July 2025: Author notification</li>
      <li>Wed, 10 September 2025: Camera Ready deadline</li>
    </ul>
    """
    deadlines = _extract_deadlines_generic(html)
    labels = {d["label"] for d in deadlines}
    assert "submission" in labels
    assert "early_reject" in labels
    assert "notification" in labels
    assert "camera_ready" in labels


def test_generic_extractor_no_dates():
    """Generic extractor returns empty on HTML with no dates."""
    html = "<p>No deadlines here, just prose about the conference.</p>"
    assert _extract_deadlines_generic(html) == []


def test_fallback_chain_specific_first():
    """Fallback: site-specific patterns used when present and matching."""
    html = """
    <h2>Important Dates</h2>
    <ul>
      <li>Paper submission deadline: June 5, 2025</li>
    </ul>
    """
    conf = {
        "name": "Test",
        "url": "https://example.com",
        "strategy": "regex",
        "tags": ["GEN"],
        "selectors": {
            "deadlines": [
                {"label": "submission", "pattern": r"Paper submission deadline:\s*(.*?)</li>"},
            ],
        },
    }

    @patch("crawler.strategies.regex.requests.get")
    def run(mock_get):
        mock_get.return_value = MagicMock(text=html)
        strategy = RegexStrategy()
        results = strategy.extract(conf, 2025)
        assert len(results) == 1
        assert results[0].deadlines == [{"label": "submission", "date": "2025-06-05 23:59"}]

    run()


def test_fallback_chain_generic_when_specific_empty():
    """Fallback: generic extractor used when specific patterns return nothing."""
    html = """
    <h2>Important Dates</h2>
    <ul>
      <li>Paper submission deadline: June 5, 2025</li>
      <li>Author notification: September 9, 2025</li>
    </ul>
    """
    conf = {
        "name": "Test",
        "url": "https://example.com",
        "strategy": "regex",
        "tags": ["GEN"],
        "selectors": {
            # Patterns that won't match this HTML
            "deadlines": [
                {"label": "submission", "pattern": r"will_not_match:\s*<strong>(.*?)</strong>"},
            ],
        },
    }

    @patch("crawler.strategies.regex.requests.get")
    def run(mock_get):
        mock_get.return_value = MagicMock(text=html)
        strategy = RegexStrategy()
        results = strategy.extract(conf, 2025)
        assert len(results) == 1
        labels = {d["label"] for d in results[0].deadlines}
        assert "submission" in labels
        assert "notification" in labels

    run()


def test_fallback_chain_generic_when_no_patterns():
    """Fallback: generic extractor used when no deadline patterns defined."""
    html = """
    <h2>Important Dates</h2>
    <ul>
      <li>Abstract registration: March 26, 2026</li>
      <li>Submission deadline: April 1, 2026</li>
    </ul>
    """
    conf = {
        "name": "Test",
        "url": "https://example.com",
        "strategy": "regex",
        "tags": ["GEN"],
        "selectors": {
            "section": "Important Dates</h2>.*?</ul>",
            # No "deadlines" key — should fall through to generic
        },
    }

    @patch("crawler.strategies.regex.requests.get")
    def run(mock_get):
        mock_get.return_value = MagicMock(text=html)
        strategy = RegexStrategy()
        results = strategy.extract(conf, 2026)
        assert len(results) == 1
        labels = {d["label"] for d in results[0].deadlines}
        assert "abstract" in labels
        assert "submission" in labels

    run()
