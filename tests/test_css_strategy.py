"""Tests for CSS selector extraction strategy (T3)."""

import pytest

from crawler.extractors.css import _extract_deadlines_css


# --- _extract_deadlines_css ---

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


def test_extract_table_with_label_date_selectors():
    selectors = {
        "section_css": "div.important-dates",
        "items": "tr",
        "label": "td:first-child",
        "date": "td:last-child",
    }
    results = _extract_deadlines_css(selectors, TABLE_HTML, year=2026)
    labels = [d["label"] for d in results]
    assert "abstract" in labels
    assert "submission" in labels
    assert "notification" in labels
    assert "camera_ready" in labels


def test_extract_table_dates_correct():
    selectors = {
        "section_css": "div.important-dates",
        "items": "tr",
        "label": "td:first-child",
        "date": "td:last-child",
    }
    results = _extract_deadlines_css(selectors, TABLE_HTML, year=2026)
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


def test_extract_dl_with_label_date_selectors():
    """DL items wrapped in divs — each div is one item with dt=label, dd=date."""
    selectors = {
        "section_css": "section#dates",
        "items": "dl div",
        "label": "dt",
        "date": "dd",
    }
    results = _extract_deadlines_css(selectors, DL_HTML, year=2026)
    labels = [d["label"] for d in results]
    assert "submission" in labels
    assert "notification" in labels
    assert "camera_ready" in labels


LIST_HTML = """
<html><body>
<ul class="cfp-dates">
  <li>Abstract registration: March 1, 2026</li>
  <li>Paper submission deadline: March 8, 2026</li>
  <li>Author notification: May 20, 2026</li>
</ul>
</body></html>
"""


def test_extract_list_no_sub_selectors():
    """No label/date sub-selectors: full item text used for both."""
    selectors = {
        "section_css": "ul.cfp-dates",
        "items": "li",
    }
    results = _extract_deadlines_css(selectors, LIST_HTML, year=2026)
    labels = [d["label"] for d in results]
    assert "abstract" in labels
    assert "submission" in labels
    assert "notification" in labels


def test_extract_list_dates_correct():
    selectors = {
        "section_css": "ul.cfp-dates",
        "items": "li",
    }
    results = _extract_deadlines_css(selectors, LIST_HTML, year=2026)
    by_label = {d["label"] for d in results}
    assert by_label == {"abstract", "submission", "notification"}


def test_section_css_missing_returns_empty():
    selectors = {"section_css": "div.nonexistent", "items": "li"}
    results = _extract_deadlines_css(selectors, LIST_HTML)
    assert results == []


def test_items_selector_missing_returns_empty():
    selectors = {"section_css": "ul.cfp-dates"}
    results = _extract_deadlines_css(selectors, LIST_HTML)
    assert results == []


def test_duplicate_labels_deduplicated():
    html = """
    <ul class="dates">
      <li>Paper submission deadline: January 10, 2026</li>
      <li>Paper submission deadline: January 17, 2026</li>
    </ul>
    """
    selectors = {"section_css": "ul.dates", "items": "li"}
    results = _extract_deadlines_css(selectors, html, year=2026)
    submission_items = [d for d in results if d["label"] == "submission"]
    assert len(submission_items) == 1


def test_header_row_skipped_no_date():
    """Table header row has no date — should be skipped without error."""
    selectors = {
        "items": "tr",
        "label": "td:first-child",
        "date": "td:last-child",
    }
    results = _extract_deadlines_css(selectors, TABLE_HTML, year=2026)
    # Header row <th> has no <td> → no date parsed → skipped
    assert all(d["date"] != "" for d in results)


def test_range_expands_to_start_and_end():
    html = """
    <ul class="dates">
      <li>Paper submission deadline: <strong>January 17, 2026</strong></li>
      <li>Rebuttal Period: <strong>November 6–13, 2025</strong></li>
      <li>Author notification: <strong>December 4, 2025</strong></li>
    </ul>
    """
    selectors = {"section_css": "ul.dates", "items": "li", "date": "strong"}
    results = _extract_deadlines_css(selectors, html, year=2026)
    by_label = {d["label"]: d["date"] for d in results}
    assert by_label.get("rebuttal_start") == "2025-11-06 23:59"
    assert by_label.get("rebuttal_end") == "2025-11-13 23:59"
    assert by_label.get("submission") == "2026-01-17 23:59"
    assert by_label.get("notification") == "2025-12-04 23:59"


def test_monthday_fallback_uses_year():
    html = """
    <ul class="dates">
      <li>Paper submission: March 8</li>
    </ul>
    """
    selectors = {"section_css": "ul.dates", "items": "li"}
    results = _extract_deadlines_css(selectors, html, year=2026)
    by_label = {d["label"]: d["date"] for d in results}
    assert by_label.get("submission") == "2026-03-08 23:59"


# --- CSS extraction with cycles ---

CYCLE_HTML = """
<html><body>
<div id="cycle1">
  <ul class="dates">
    <li>Paper submission deadline: January 10, 2026</li>
    <li>Author notification: March 1, 2026</li>
  </ul>
</div>
<div id="cycle2">
  <ul class="dates">
    <li>Paper submission deadline: July 10, 2026</li>
    <li>Author notification: September 1, 2026</li>
  </ul>
</div>
</body></html>
"""


def test_css_cycles():
    c1_sel = {"section_css": "div#cycle1 ul.dates", "items": "li"}
    c2_sel = {"section_css": "div#cycle2 ul.dates", "items": "li"}

    c1_dl = _extract_deadlines_css(c1_sel, CYCLE_HTML, year=2026)
    c2_dl = _extract_deadlines_css(c2_sel, CYCLE_HTML, year=2026)

    c1_labels = {d["label"] for d in c1_dl}
    assert "submission" in c1_labels
    assert "notification" in c1_labels

    c2_labels = {d["label"] for d in c2_dl}
    assert "submission" in c2_labels
    assert "notification" in c2_labels
