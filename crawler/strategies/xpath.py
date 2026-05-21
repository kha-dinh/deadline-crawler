"""XPath expression-based extraction strategy (T28).

Config shape (selectors block):
  section_xpath: "//div[@class='important-dates']"  # XPath to narrow DOM (optional)
  items: "//tr"                                      # XPath for each deadline item
  label: "td[1]"                                     # XPath sub-expression for label within item (optional)
  date: "td[last()]"                                 # XPath sub-expression for date within item (optional)

If label/date sub-expressions are omitted, full item text is used:
  label — matched via LABEL_MAP (_match_label)
  date  — extracted via _GENERIC_DATE_RE + _parse_deadline_date
"""

from __future__ import annotations

import warnings
from datetime import datetime

import lxml.html

from crawler.config import resolve_url
from crawler.labels import _match_label
from crawler.models import CrawlResult
from crawler.strategy import BaseStrategy
from crawler.strategies.regex import (
    _GENERIC_DATE_RE,
    _DATE_RANGE_RE,
    _DATE_RANGE_EXPANDED_RE,
    _RANGE_LABEL_PAIRS,
    _check_date_year_sanity,
    _fetch,
    _is_scaffolding,
    _parse_deadline_date,
    _resolve_event_selectors,
    _build_cycle_selectors,
    _split_date_range,
)


def _element_text(el) -> str:
    """Get all text content of an lxml element, stripped."""
    return (el.text_content() or "").strip()


def _extract_deadlines_xpath(selectors: dict, html: str, year: int | None = None) -> list[dict]:
    """Extract deadlines using XPath expressions.

    selectors keys:
      section_xpath — narrow DOM to this element before searching
      items         — XPath for each deadline item (required)
      label         — sub-expression for label text within item (optional, relative XPath)
      date          — sub-expression for date text within item (optional, relative XPath)
    """
    doc = lxml.html.fromstring(html)

    # Narrow to section if section_xpath provided
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
            # Check for date range
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
            # Check for date range in full item text
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
                from crawler.strategies.regex import _MONTHDAY_RE
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

    # Post-process: fix year-inference errors (same logic as CSS strategy)
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


class XpathStrategy(BaseStrategy):
    name = "xpath"

    def extract(self, conf: dict, year: int) -> list[CrawlResult]:
        url = resolve_url(conf, year)
        if not url:
            raise ValueError(f"{conf['name']}: no URL configured")

        html = _fetch(url)

        if _is_scaffolding(html):
            raise ValueError(f"{conf['name']}: scaffolding/placeholder page detected at {url}")

        date, place = self._extract_main_fields(conf, year, url, html)

        cycles = conf.get("cycles")
        if cycles:
            results = []
            for cycle in cycles:
                deadlines = _extract_deadlines_xpath(
                    _build_cycle_selectors(conf, cycle), html, year
                )
                _check_date_year_sanity(deadlines, year, conf["name"], url)
                results.append(
                    CrawlResult(
                        name=conf["name"],
                        year=year,
                        link=url,
                        deadlines=deadlines,
                        cycle=cycle.get("name"),
                        date=date,
                        place=place,
                        description=conf.get("description"),
                        area=conf.get("area", ""),
                        rank=conf.get("rank", "unknown"),
                    )
                )
            return results
        else:
            deadlines = _extract_deadlines_xpath(
                conf.get("selectors", {}), html, year
            )
            _check_date_year_sanity(deadlines, year, conf["name"], url)
            return [
                CrawlResult(
                    name=conf["name"],
                    year=year,
                    link=url,
                    deadlines=deadlines,
                    date=date,
                    place=place,
                    description=conf.get("description"),
                    area=conf.get("area", ""),
                    rank=conf.get("rank", "unknown"),
                )
            ]

    def _extract_main_fields(
        self, conf: dict, year: int, cfp_url: str, cfp_html: str
    ) -> tuple[str | None, str | None]:
        event_selectors = _resolve_event_selectors(conf)
        static_date = conf.get("date") or None
        static_place = conf.get("place") or None

        if not event_selectors:
            return static_date, static_place

        url_main = resolve_url(
            {"url": conf.get("url_main", conf.get("url"))}, year
        )
        if url_main and url_main != cfp_url:
            main_html = _fetch(url_main)
        else:
            main_html = cfp_html

        # Use lxml for XPath-based event field extraction if xpath selectors provided;
        # fall back to CSS via BeautifulSoup for CSS-style event_selectors
        doc = lxml.html.fromstring(main_html)
        date = self._xpath_text(doc, event_selectors.get("date")) or static_date
        place = self._xpath_text(doc, event_selectors.get("place")) or static_place
        if date and place and date.endswith(place):
            date = date[: -len(place)].strip()
        return date, place

    @staticmethod
    def _xpath_text(doc, expr: str | None) -> str | None:
        """Extract text from first XPath match. Also supports CSS selectors for compat."""
        if not expr:
            return None
        # If it looks like a CSS selector (starts with . or #, or has no /),
        # use cssselect for compatibility with event_selectors defaults
        if not expr.startswith("/") and not expr.startswith("("):
            from lxml.cssselect import CSSSelector
            sel = CSSSelector(expr)
            els = sel(doc)
            return _element_text(els[0]) if els else None
        els = doc.xpath(expr)
        if not els:
            return None
        if isinstance(els[0], str):
            return els[0].strip() or None
        return _element_text(els[0]) or None
