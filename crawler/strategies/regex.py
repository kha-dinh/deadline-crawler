"""Regex-based extraction strategy (T4)."""

import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from crawler.config import resolve_url
from crawler.models import CrawlResult
from crawler.strategy import BaseStrategy

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def _parse_deadline_date(text: str) -> str | None:
    """Parse a human-readable date string into V2 format 'YYYY-MM-DD HH:MM'.

    Handles formats like:
      - "Tuesday, August 26, 2025, 11:59 pm AoE"
      - "Thursday, February 5, 2026"
      - "Jan 7, 2026"
      - "Wed, 23 April 2025"
      - "June 5, 2025"
    """
    text = text.strip()
    # Remove day-of-week prefix if present (e.g. "Tuesday, " or "Wed, ")
    text = re.sub(r"^[A-Z][a-z]+(?:day)?,\s*", "", text)
    # Normalize non-standard abbreviations (e.g. "Sept" → "Sep")
    text = re.sub(r"\bSept\b", "Sep", text)

    # Strip trailing qualifier words (mandatory, etc.)
    text = re.sub(r"\s+(?:mandatory|optional)\b.*$", "", text, flags=re.IGNORECASE)

    # Strip timezone suffix after am/pm or at end
    cleaned = re.sub(r"\s+(?:AoE|UTC|EST|PST|PT|ET|AOE)\s*$", "", text.strip())

    # Try formats with explicit time first
    for fmt in (
        "%B %d, %Y, %I:%M %p",
        "%B %d, %Y, %I:%M%p",
        "%b %d, %Y, %I:%M %p",
        "%b %d, %Y, %I:%M%p",
    ):
        try:
            dt = datetime.strptime(cleaned.strip(), fmt)
            return dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue

    # Date-only formats — default to 23:59 (end of day, AoE convention)
    for fmt in (
        "%B %d, %Y",     # August 26, 2025
        "%b %d, %Y",     # Aug 26, 2025
        "%d %B %Y",      # 23 April 2025
        "%d %b %Y",      # 23 Apr 2025
    ):
        try:
            dt = datetime.strptime(cleaned.strip(), fmt)
            return dt.replace(hour=23, minute=59).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue

    return None


def _fetch(url: str) -> str:
    return requests.get(url, headers=_HEADERS, timeout=30).text


class RegexStrategy(BaseStrategy):
    name = "regex"

    def extract(self, conf: dict, year: int) -> list[CrawlResult]:
        url = resolve_url(conf, year)
        if not url:
            raise ValueError(f"{conf['name']}: no URL configured")

        html = _fetch(url)

        # Shared fields from main page
        date, place = self._extract_main_fields(conf, year, url, html)
        overrides = conf.get("overrides", {})

        cycles = conf.get("cycles")
        if cycles:
            # One CrawlResult per cycle
            results = []
            for cycle in cycles:
                deadlines = self._extract_deadlines(cycle.get("selectors", {}), html)
                results.append(CrawlResult(
                    name=conf["name"],
                    year=year,
                    link=url,
                    deadlines=deadlines,
                    cycle=cycle.get("name"),
                    date=date,
                    place=place,
                    description=overrides.get("description"),
                    tags=list(conf.get("tags", [])),
                ))
            return results
        else:
            # No cycles — single result using top-level selectors
            deadlines = self._extract_deadlines(conf.get("selectors", {}), html)
            return [CrawlResult(
                name=conf["name"],
                year=year,
                link=url,
                deadlines=deadlines,
                date=date,
                place=place,
                description=overrides.get("description"),
                tags=list(conf.get("tags", [])),
            )]

    def _extract_main_fields(
        self, conf: dict, year: int, cfp_url: str, cfp_html: str
    ) -> tuple[str | None, str | None]:
        main_selectors = conf.get("main_selectors")
        if not main_selectors:
            return None, None

        url_main = resolve_url(
            {"url": conf.get("url_main", conf.get("url"))}, year
        )
        if url_main and url_main != cfp_url:
            main_html = _fetch(url_main)
        else:
            main_html = cfp_html

        soup = BeautifulSoup(main_html, "html.parser")
        date = self._css_text(soup, main_selectors.get("date"))
        place = self._css_text(soup, main_selectors.get("place"))
        return date, place

    @staticmethod
    def _extract_deadlines(selectors: dict, html: str) -> list[dict]:
        # Optionally narrow HTML to a section first
        section_pattern = selectors.get("section")
        if section_pattern:
            m = re.search(section_pattern, html, re.DOTALL | re.IGNORECASE)
            if m:
                html = m.group(0)
            else:
                return []

        deadline_specs = selectors.get("deadlines", [])
        if not deadline_specs:
            return []

        deadlines = []
        seen_dates = set()
        for spec in deadline_specs:
            label = spec["label"]
            pattern = spec["pattern"]
            matches = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)
            for match in matches:
                parsed = _parse_deadline_date(match)
                if parsed and parsed not in seen_dates:
                    seen_dates.add(parsed)
                    deadlines.append({"label": label, "date": parsed})
        return deadlines

    @staticmethod
    def _css_text(soup: BeautifulSoup, selector: str | None) -> str | None:
        if not selector:
            return None
        el = soup.select_one(selector)
        return el.get_text(strip=True) if el else None
