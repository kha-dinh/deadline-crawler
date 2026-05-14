"""Regex-based extraction strategy (T4, T16)."""

import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from crawler.config import resolve_url
from crawler.models import CrawlResult
from crawler.strategy import BaseStrategy

# V10/V11: Canonical label map — maps raw CFP phrases → canonical labels.
# Each canonical label has ≥1 phrase variant. Single source of truth.
LABEL_MAP: dict[str, list[str]] = {
    "abstract": [
        "abstract registration",
        "register abstracts",
        "abstracts due",
        "abstract submission",
        "abstract deadline",
        "paper titles and abstracts due",
    ],
    "submission": [
        "submission deadline",
        "paper submission",
        "paper submissions due",
        "full paper submission",
        "submissions due",
        "paper due",
    ],
    "early_reject": [
        "early reject",
        "early rejection",
        "early-reject",
        "desk reject",
    ],
    "rebuttal_start": [
        "rebuttal start",
        "rebuttal period begin",
        "rebuttal begins",
        "reviews available",
        "author response start",
    ],
    "rebuttal_end": [
        "rebuttal end",
        "rebuttal due",
        "rebuttal deadline",
        "author response due",
        "author responses due",
    ],
    "notification": [
        "author notification",
        "notification to authors",
        "notification of acceptance",
        "acceptance notification",
        "decision notification",
    ],
    "shepherd": [
        "shepherd",
        "shepherding",
        "conditional accept",
    ],
    "camera_ready": [
        "camera ready",
        "camera-ready",
        "final paper",
        "final version",
        "final papers due",
    ],
}

# Generic date pattern: matches "Month DD, YYYY" with optional ordinal suffix
_GENERIC_DATE_RE = re.compile(
    r"([A-Z][a-z]+\.?\s+\d+\w*,?\s+\d{4})"
    r"|(\d+\w*\s+[A-Z][a-z]+\.?\s+\d{4})"
)

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
    # Normalize HTML entities to plain text
    text = text.replace("&nbsp;", " ").replace("&#8212;", "—")
    # Collapse multiple spaces
    text = re.sub(r" {2,}", " ", text)
    # Remove day-of-week prefix if present (e.g. "Tuesday, " or "Wed, ")
    text = re.sub(r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s*", "", text)
    # Normalize non-standard abbreviations (e.g. "Sept" → "Sep")
    text = re.sub(r"\bSept\b", "Sep", text)
    # Strip ordinal suffixes (e.g. "3rd" → "3", "1st" → "1")
    text = re.sub(r"(\d+)(?:st|nd|rd|th)\b", r"\1", text)

    # Strip trailing qualifier words (mandatory, etc.)
    text = re.sub(r"\s+(?:mandatory|optional)\b.*$", "", text, flags=re.IGNORECASE)
    # Strip parenthetical suffixes like "(previously ...)" or "(AoE)"
    text = re.sub(r"\s*\(.*?\)\s*$", "", text)
    # Strip semicolon-delimited time (e.g. "April 10, 2025; 23:59 PT")
    text = re.sub(r";\s*\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?\s*(?:AoE|UTC|EST|PST|PDT|PT|ET|AOE)?\s*$", "", text)

    # Strip timezone suffix after am/pm or at end (handles "US PDT", "EST", etc.)
    cleaned = re.sub(r"\s+(?:US\s+)?(?:AoE|UTC|EST|EDT|PST|PDT|PT|ET|AOE|Eastern|Pacific)\s*$", "", text.strip(), flags=re.IGNORECASE)

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


def _strip_html(html: str) -> str:
    """Strip HTML tags, collapse whitespace, return plain text lines."""
    # Remove script/style blocks
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Replace block-level tags with newlines
    text = re.sub(r"<(?:br|li|tr|p|div|h[1-6])[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode common entities
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#8212;", "—")
    # Collapse whitespace within lines
    text = re.sub(r"[ \t]+", " ", text)
    return text


def _match_label(text: str) -> str | None:
    """Match a text fragment against LABEL_MAP, return canonical label or None."""
    lower = text.lower()
    for label, phrases in LABEL_MAP.items():
        for phrase in phrases:
            if phrase in lower:
                return label
    return None


def _extract_deadlines_specific(deadline_specs: list[dict], html: str) -> list[dict]:
    """Extract deadlines using site-specific regex patterns."""
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


def _extract_deadlines_generic(html: str) -> list[dict]:
    """Generic text-based deadline extraction (T16).

    Strips HTML, scans each line for a known label phrase + date pattern.
    Uses LABEL_MAP for phrase→canonical label mapping.
    """
    text = _strip_html(html)
    deadlines = []
    seen_labels = set()

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue

        label = _match_label(line)
        if not label or label in seen_labels:
            continue

        # Find a date on this line
        m = _GENERIC_DATE_RE.search(line)
        if not m:
            continue

        date_str = m.group(1) or m.group(2)
        parsed = _parse_deadline_date(date_str)
        if parsed:
            seen_labels.add(label)
            deadlines.append({"label": label, "date": parsed})

    return deadlines


def _fetch(url: str) -> str:
    resp = requests.get(url, headers=_HEADERS, timeout=30)
    resp.encoding = resp.apparent_encoding
    return resp.text


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

        # Fallback chain: site-specific patterns → generic text extractor → empty
        deadline_specs = selectors.get("deadlines", [])
        if deadline_specs:
            result = _extract_deadlines_specific(deadline_specs, html)
            if result:
                return result

        # Generic text-based extraction (T16)
        return _extract_deadlines_generic(html)

    @staticmethod
    def _css_text(soup: BeautifulSoup, selector: str | None) -> str | None:
        if not selector:
            return None
        el = soup.select_one(selector)
        return el.get_text(strip=True) if el else None
