"""XPath expression-based extraction functions (T28).

Pure functions — no network I/O. Takes HTML strings, returns deadline data.

Config shape (selectors block):
  section_xpath: "//div[@class='important-dates']"  # XPath to narrow DOM (optional)
  items: "//tr"                                      # XPath for each deadline item
  label: "td[1]"                                     # XPath sub-expression for label (optional)
  date: "td[last()]"                                 # XPath sub-expression for date (optional)
"""

from __future__ import annotations

import warnings
from datetime import datetime

import lxml.html

from crawler.labels import _match_label
from crawler.extractors.regex import (
    _GENERIC_DATE_RE,
    _DATE_RANGE_RE,
    _DATE_RANGE_EXPANDED_RE,
    _RANGE_LABEL_PAIRS,
    _MONTHDAY_RE,
    _parse_deadline_date,
    _split_date_range,
)


def _element_text(el) -> str:
    """Get all text content of an lxml element, stripped."""
    return (el.text_content() or "").strip()


def _extract_deadlines_xpath(selectors: dict, html: str, year: int | None = None) -> list[dict]:
    """Extract deadlines using XPath expressions."""
    doc = lxml.html.fromstring(html)

    section_xpath = selectors.get("section_xpath")
    if section_xpath:
        containers = doc.xpath(section_xpath)
        if not containers:
            return []
        doc = containers[0]

    items_xpath = selectors.get("items")
    if not items_xpath:
        return []

    items = doc.xpath(items_xpath)
    label_xpath = selectors.get("label")
    date_xpath = selectors.get("date")

    deadlines: list[dict] = []
    seen_labels: set[str] = set()
    inferred_year_labels: set[str] = set()

    for item in items:
        item_text = _element_text(item)

        # --- label extraction ---
        if label_xpath:
            label_els = item.xpath(label_xpath)
            label_text = _element_text(label_els[0]) if label_els else item_text
        else:
            label_text = item_text
        label = _match_label(label_text)

        # --- date extraction (with range support) ---
        year_inferred = False
        if date_xpath:
            date_els = item.xpath(date_xpath)
            date_text = _element_text(date_els[0]) if date_els else ""
            _rm = _DATE_RANGE_RE.search(date_text) or _DATE_RANGE_EXPANDED_RE.search(date_text)
            range_result = _split_date_range(_rm.group(0)) if _rm else None
            if range_result:
                start_str, end_str = range_result
                ps = _parse_deadline_date(start_str)
                pe = _parse_deadline_date(end_str)
                if label and ps and label not in seen_labels:
                    seen_labels.add(label)
                    deadlines.append({"label": label, "date": ps})
                    partner = _RANGE_LABEL_PAIRS.get(label)
                    if partner and pe and partner not in seen_labels:
                        seen_labels.add(partner)
                        deadlines.append({"label": partner, "date": pe})
                continue
            parsed = _parse_deadline_date(date_text)
        else:
            _rm = _DATE_RANGE_RE.search(item_text) or _DATE_RANGE_EXPANDED_RE.search(item_text)
            range_result = _split_date_range(_rm.group(0)) if _rm else None
            if range_result:
                start_str, end_str = range_result
                ps = _parse_deadline_date(start_str)
                pe = _parse_deadline_date(end_str)
                if label and ps and label not in seen_labels:
                    seen_labels.add(label)
                    deadlines.append({"label": label, "date": ps})
                    partner = _RANGE_LABEL_PAIRS.get(label)
                    if partner and pe and partner not in seen_labels:
                        seen_labels.add(partner)
                        deadlines.append({"label": partner, "date": pe})
                continue
            m = _GENERIC_DATE_RE.search(item_text)
            if m:
                date_str = m.group(1) or m.group(2)
                tail = item_text[m.start():]
                parsed = _parse_deadline_date(tail) or _parse_deadline_date(date_str)
            elif year:
                md = _MONTHDAY_RE.search(item_text)
                parsed = _parse_deadline_date(f"{md.group(1)}, {year}") if md else None
                year_inferred = parsed is not None
            else:
                parsed = None

        if label and parsed and label not in seen_labels:
            seen_labels.add(label)
            deadlines.append({"label": label, "date": parsed})
            if year_inferred:
                inferred_year_labels.add(label)

    # Post-process: fix year-inference errors
    notif = next((d["date"] for d in deadlines if d["label"] == "notification"), None)
    if notif:
        for d in deadlines:
            if d["label"] in inferred_year_labels and d["date"] > notif:
                try:
                    dt = datetime.strptime(d["date"], "%Y-%m-%d %H:%M")
                    corrected = dt.replace(year=dt.year - 1).strftime("%Y-%m-%d %H:%M")
                    if corrected < notif:
                        d["date"] = corrected
                except (ValueError, OverflowError):
                    pass

    return deadlines
