"""CSS selector-based extraction strategy (T3).

Config shape (selectors block):
  section_css: "div.important-dates"  # CSS selector to narrow DOM (optional)
  items: "tr"                          # CSS selector for each deadline item
  label: "td:first-child"             # CSS sub-selector for label within item (optional)
  date: "td:last-child"               # CSS sub-selector for date within item (optional)

If label/date sub-selectors are omitted, full item text is used:
  label — matched via LABEL_MAP (_match_label)
  date  — extracted via _GENERIC_DATE_RE + _parse_deadline_date
"""

from __future__ import annotations

import warnings

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from crawler.config import resolve_url
from crawler.labels import _match_label
from crawler.models import CrawlResult
from crawler.strategy import BaseStrategy
from crawler.strategies.regex import (
    _GENERIC_DATE_RE,
    _DATE_RANGE_RE,
    _DATE_RANGE_EXPANDED_RE,
    _RANGE_LABEL_PAIRS,
    _fetch,
    _is_scaffolding,
    _parse_deadline_date,
    _resolve_event_selectors,
    _build_cycle_selectors,
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
        if date_sel:
            date_el = item.select_one(date_sel)
            date_text = date_el.get_text(strip=True) if date_el else ""
            # Check for date range (compact or expanded format)
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
            # Check for date range in full item text before trying single-date extraction
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
            else:
                parsed = None

        if label and parsed and label not in seen_labels:
            seen_labels.add(label)
            deadlines.append({"label": label, "date": parsed})

    return deadlines


class CssStrategy(BaseStrategy):
    name = "css"

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
                deadlines = _extract_deadlines_css(
                    _build_cycle_selectors(conf, cycle), html, year
                )
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
                        tags=list(conf.get("tags", [])),
                    )
                )
            return results
        else:
            deadlines = _extract_deadlines_css(
                conf.get("selectors", {}), html, year
            )
            return [
                CrawlResult(
                    name=conf["name"],
                    year=year,
                    link=url,
                    deadlines=deadlines,
                    date=date,
                    place=place,
                    description=conf.get("description"),
                    tags=list(conf.get("tags", [])),
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

        soup = BeautifulSoup(main_html, "lxml")
        date = self._css_text(soup, event_selectors.get("date")) or static_date
        place = self._css_text(soup, event_selectors.get("place")) or static_place
        if date and place and date.endswith(place):
            date = date[: -len(place)].strip()
        return date, place

    @staticmethod
    def _css_text(soup: BeautifulSoup, selector: str | None) -> str | None:
        if not selector:
            return None
        el = soup.select_one(selector)
        return el.get_text(strip=True) if el else None
