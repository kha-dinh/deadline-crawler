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
        "mandatory registration",
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
        "author response period",
        "authors response period",
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
        "notification",
    ],
    "shepherd": [
        "shepherd",
        "shepherding",
        "conditional accept",
        "minor revision",
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
        "%B %d %Y",      # August 26 2025 (no comma)
        "%b %d %Y",      # Aug 26 2025 (no comma)
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
    """Structure-preserving HTML→text (Phase A, T17).

    Preserves label+date pairing by:
    - Joining <td>/<th> cells in same <tr> with ' | '
    - Merging <dt> + <dd> pairs onto one line
    - Flattening <li> inline children (incl <strong>, <br>) onto one line
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove script/style blocks
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()

    # Replace <br> with space to keep inline content on one line
    for br in soup.find_all("br"):
        br.replace_with(" ")

    # Process <tr>: join cells with ' | '
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if cells:
            text = " | ".join(c.get_text(separator=" ", strip=True) for c in cells)
            tr.replace_with(text + "\n")

    # Process <dt>/<dd> pairs: merge onto one line
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        dt_text = dt.get_text(strip=True)
        dd_text = dd.get_text(strip=True) if dd else ""
        dt.replace_with(f"{dt_text} | {dd_text}\n")
        if dd:
            dd.decompose()

    # Process <li>: flatten all inline children onto one line
    for li in soup.find_all("li"):
        text = li.get_text(separator=" ", strip=True)
        li.replace_with(text + "\n")

    # Get remaining text with newlines at block boundaries
    text = soup.get_text(separator="\n")

    # Clean up entities and whitespace
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#8212;", "—")
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            lines.append(line)

    return "\n".join(lines)


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


# Matches "Month DD" without year (e.g. "May 30", "July 14", "August 18-22")
_MONTHDAY_RE = re.compile(
    r"([A-Z][a-z]+\.?\s+\d+)(?:\s|,|$|-)"
)


def _extract_deadlines_generic(html: str, year: int | None = None) -> list[dict]:
    """Generic two-pass deadline extraction (Phase A+C, T17).

    Phase A: structure-preserving HTML→text (via _strip_html).
    Phase C: two-pass proximity search:
      Pass 1 — find all lines with date-like strings.
      Pass 2 — for each date, search same line + ±2 lines for label phrase.
      Nearest label wins; same label not assigned twice.
    """
    text = _strip_html(html)
    lines = text.split("\n")
    deadlines = []
    seen_labels: set[str] = set()

    # Pass 1: find all (line_index, parsed_date) tuples
    date_hits: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = _GENERIC_DATE_RE.search(line)
        if m:
            date_str = m.group(1) or m.group(2)
            parsed = _parse_deadline_date(date_str)
            if parsed:
                date_hits.append((i, parsed))
        elif year:
            # Fallback: try month+day without year, append conference year
            md = _MONTHDAY_RE.search(line)
            if md:
                date_with_year = f"{md.group(1)}, {year}"
                parsed = _parse_deadline_date(date_with_year)
                if parsed:
                    date_hits.append((i, parsed))

    # Pass 2a: same-line matches first (prevents proximity from stealing labels)
    matched_indices: set[int] = set()
    for line_idx, parsed_date in date_hits:
        label = _match_label(lines[line_idx])
        if label and label not in seen_labels:
            seen_labels.add(label)
            deadlines.append({"label": label, "date": parsed_date})
            matched_indices.add(line_idx)

    # Pass 2b: proximity search for remaining unmatched dates
    for line_idx, parsed_date in date_hits:
        if line_idx in matched_indices:
            continue
        best_label = None
        for dist in range(1, 3):  # ±1, ±2 lines
            if best_label:
                break
            for check_idx in [line_idx - dist, line_idx + dist]:
                if 0 <= check_idx < len(lines):
                    label = _match_label(lines[check_idx])
                    if label and label not in seen_labels:
                        best_label = label
                        break
        if best_label:
            seen_labels.add(best_label)
            deadlines.append({"label": best_label, "date": parsed_date})

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
                deadlines = self._extract_deadlines(cycle.get("selectors", {}), html, year)
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
            deadlines = self._extract_deadlines(conf.get("selectors", {}), html, year)
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
    def _extract_deadlines(selectors: dict, html: str, year: int | None = None) -> list[dict]:
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
        return _extract_deadlines_generic(html, year=year)

    @staticmethod
    def _css_text(soup: BeautifulSoup, selector: str | None) -> str | None:
        if not selector:
            return None
        el = soup.select_one(selector)
        return el.get_text(strip=True) if el else None
