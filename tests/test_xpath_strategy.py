"""Tests for XPath expression extraction strategy (T28)."""

import pytest

from crawler.extractors.xpath import _extract_deadlines_xpath
from crawler.extractors.regex import _is_scaffolding


# --- _extract_deadlines_xpath ---

TABLE_HTML = """
<html><body>
<div class="important-dates">
  <table>
    <tr><th>Milestone</th><th>Date</th></tr>
    <tr><td>Abstract registration</td><td>January 10, 2026</td></tr>
    <tr><td>Paper submission deadline</td><td>January 17, 2026</td></tr>
    <tr><td>Author notification</td><td>March 15, 2026</td></tr>
    <tr><td>Camera ready</td><td>April 5, 2026</td></tr>
  </table>
</div>
</body></html>
"""


def test_extract_table_with_label_date_xpath():
    selectors = {
        "section_xpath": "//div[@class='important-dates']",
        "items": ".//tr",
        "label": "td[1]",
        "date": "td[last()]",
    }
    results = _extract_deadlines_xpath(selectors, TABLE_HTML, year=2026)
    labels = [d["label"] for d in results]
    assert "abstract" in labels
    assert "submission" in labels
    assert "notification" in labels
    assert "camera_ready" in labels


def test_extract_table_dates_correct():
    selectors = {
        "section_xpath": "//div[@class='important-dates']",
        "items": ".//tr",
        "label": "td[1]",
        "date": "td[last()]",
    }
    results = _extract_deadlines_xpath(selectors, TABLE_HTML, year=2026)
    by_label = {d["label"]: d["date"] for d in results}
    assert by_label["abstract"] == "2026-01-10 23:59"
    assert by_label["submission"] == "2026-01-17 23:59"
    assert by_label["notification"] == "2026-03-15 23:59"
    assert by_label["camera_ready"] == "2026-04-05 23:59"


DL_HTML = """
<html><body>
<section id="dates">
  <dl>
    <div><dt>Paper submission</dt><dd>February 20, 2026</dd></div>
    <div><dt>Notification to authors</dt><dd>April 10, 2026</dd></div>
    <div><dt>Camera-ready deadline</dt><dd>May 1, 2026</dd></div>
  </dl>
</section>
</body></html>
"""


def test_extract_dl_with_xpath():
    """DL items wrapped in divs — each div is one item with dt=label, dd=date."""
    selectors = {
        "section_xpath": "//section[@id='dates']",
        "items": ".//dl/div",
        "label": "dt",
        "date": "dd",
    }
    results = _extract_deadlines_xpath(selectors, DL_HTML, year=2026)
    labels = [d["label"] for d in results]
    assert "submission" in labels
    assert "notification" in labels
    assert "camera_ready" in labels


def test_extract_no_section_match():
    selectors = {
        "section_xpath": "//div[@id='nonexistent']",
        "items": ".//tr",
    }
    results = _extract_deadlines_xpath(selectors, TABLE_HTML, year=2026)
    assert results == []


def test_extract_no_items_xpath():
    selectors = {
        "section_xpath": "//div[@class='important-dates']",
    }
    results = _extract_deadlines_xpath(selectors, TABLE_HTML, year=2026)
    assert results == []


def test_extract_without_label_date_subexpr():
    """Without sub-expressions, uses full item text for both label and date matching."""
    selectors = {
        "section_xpath": "//div[@class='important-dates']",
        "items": ".//tr",
    }
    results = _extract_deadlines_xpath(selectors, TABLE_HTML, year=2026)
    # Should still find labels from full text of each row
    labels = [d["label"] for d in results]
    assert len(labels) >= 3  # at least submission, notification, camera_ready


LIST_HTML = """
<html><body>
<div id="cfp">
  <ul>
    <li><strong>Abstract registration:</strong> January 10, 2026</li>
    <li><strong>Paper submission:</strong> January 17, 2026</li>
    <li><strong>Author notification:</strong> March 15, 2026</li>
  </ul>
</div>
</body></html>
"""


def test_extract_list_items():
    selectors = {
        "section_xpath": "//div[@id='cfp']",
        "items": ".//li",
    }
    results = _extract_deadlines_xpath(selectors, LIST_HTML, year=2026)
    labels = [d["label"] for d in results]
    assert "abstract" in labels
    assert "submission" in labels
    assert "notification" in labels


RANGE_HTML = """
<html><body>
<div id="dates">
  <table>
    <tr><td>Rebuttal period</td><td>April 27 - April 29, 2026</td></tr>
    <tr><td>Author notification</td><td>May 15, 2026</td></tr>
  </table>
</div>
</body></html>
"""


def test_extract_date_range():
    selectors = {
        "section_xpath": "//div[@id='dates']",
        "items": ".//tr",
        "label": "td[1]",
        "date": "td[last()]",
    }
    results = _extract_deadlines_xpath(selectors, RANGE_HTML, year=2026)
    labels = [d["label"] for d in results]
    assert "rebuttal_start" in labels
    assert "rebuttal_end" in labels
    assert "notification" in labels


def test_duplicate_label_dedupe():
    """Same label appearing twice — only first should be kept."""
    html = """
    <html><body>
    <div id="d">
      <table>
        <tr><td>Paper submission</td><td>January 10, 2026</td></tr>
        <tr><td>Paper submission</td><td>January 17, 2026</td></tr>
        <tr><td>Author notification</td><td>March 15, 2026</td></tr>
      </table>
    </div>
    </body></html>
    """
    selectors = {
        "section_xpath": "//div[@id='d']",
        "items": ".//tr",
        "label": "td[1]",
        "date": "td[last()]",
    }
    results = _extract_deadlines_xpath(selectors, html, year=2026)
    submission_dates = [d["date"] for d in results if d["label"] == "submission"]
    assert len(submission_dates) == 1
    assert submission_dates[0] == "2026-01-10 23:59"


# --- XPath extraction integration ---

def test_xpath_basic():
    selectors = {
        "section_xpath": "//div[@class='important-dates']",
        "items": ".//tr",
        "label": "td[1]",
        "date": "td[last()]",
    }
    results = _extract_deadlines_xpath(selectors, TABLE_HTML, year=2026)
    labels = [d["label"] for d in results]
    assert "abstract" in labels
    assert "submission" in labels


def test_scaffolding_detected():
    html = "<html><body>Coming soon! Check back later.</body></html>"
    assert _is_scaffolding(html) is True


# --- XPath-specific advanced expressions ---

NESTED_HTML = """
<html><body>
<div class="content">
  <div class="dates-section">
    <h2>Important Dates</h2>
    <table class="schedule">
      <tbody>
        <tr class="deadline"><td class="event">Abstract registration</td><td class="when">January 10, 2026</td></tr>
        <tr class="info"><td colspan="2">All times AoE</td></tr>
        <tr class="deadline"><td class="event">Paper submission</td><td class="when">January 17, 2026</td></tr>
        <tr class="deadline"><td class="event">Author notification</td><td class="when">March 15, 2026</td></tr>
      </tbody>
    </table>
  </div>
</div>
</body></html>
"""


def test_xpath_class_filter():
    """XPath can filter by class — only tr[@class='deadline'], skipping info rows."""
    selectors = {
        "section_xpath": "//div[@class='dates-section']",
        "items": ".//tr[@class='deadline']",
        "label": "td[@class='event']",
        "date": "td[@class='when']",
    }
    results = _extract_deadlines_xpath(selectors, NESTED_HTML, year=2026)
    labels = [d["label"] for d in results]
    assert "abstract" in labels
    assert "submission" in labels
    assert "notification" in labels
    assert len(results) == 3  # no info row


def test_xpath_position_predicate():
    """XPath position() predicate to select specific rows."""
    selectors = {
        "section_xpath": "//table[@class='schedule']",
        "items": ".//tr[position() > 0]",
        "label": "td[1]",
        "date": "td[2]",
    }
    results = _extract_deadlines_xpath(selectors, NESTED_HTML, year=2026)
    # Should find at least the deadline rows that have valid dates
    assert len(results) >= 3
