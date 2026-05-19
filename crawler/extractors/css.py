"""CSS selector-based extraction functions (T3).

Pure functions — no network I/O. Takes HTML strings, returns deadline data.

Config shape (selectors block):
  section_css: "div.important-dates"  # CSS selector to narrow DOM (optional)
  items: "tr"                          # CSS selector for each deadline item
  label: "td:first-child"             # CSS sub-selector for label within item (optional)
  date: "td:last-child"               # CSS sub-selector for date within item (optional)
"""

from __future__ import annotations

import warnings
from datetime import datetime

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

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


def _extract_deadlines_css(selectors: dict, html: str, year: int | None = None) -> list[dict]:
    """Extract deadlines using CSS selectors.

    selectors keys:
      section_css — narrow DOM to this element before searching
      items       — selector for each deadline item (required)
      label       — sub-selector for label text within item (optional)
      date        — sub-selector for date text within item (optional)
    """
    soup = BeautifulSoup(html, "lxml")

    # Narrow to section if section_css provided
    section_sel = selectors.get("section_css")
    if section_sel:
        container = soup.select_one(section_sel)
        if container is None:
            return []
        soup = container  # type: ignore[assignment]

    items_sel = selectors.get("items")
    if not items_sel:
        return []

    items = soup.select(items_sel)
    label_sel = selectors.get("label")
    date_sel = selectors.get("date")

    deadlines: list[dict] = []
    seen_labels: set[str] = set()
    inferred_year_labels: set[str] = set()

    for item in items:
        item_text = item.get_text(separator=" ", strip=True)

        # --- label extraction ---
        if label_sel:
            label_el = item.select_one(label_sel)
            label_text = label_el.get_text(strip=True) if label_el else item_text
        else:
            label_text = item_text
        label = _match_label(label_text)

        # --- date extraction (with range support) ---
        year_inferred = False
        if date_sel:
            date_el = item.select_one(date_sel)
            date_text = date_el.get_text(strip=True) if date_el else ""
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
