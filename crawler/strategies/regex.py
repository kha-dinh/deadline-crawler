"""Regex-based extraction strategy (T4, T16)."""

import re
import threading
import warnings
from datetime import datetime

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from crawler.config import resolve_url
from crawler.labels import _match_label
from crawler.models import CrawlResult
from crawler.strategy import BaseStrategy

# Thread-local HTTP session — reuses TCP connections within each worker thread.
_thread_local = threading.local()


def _get_session() -> requests.Session:
    if not hasattr(_thread_local, "session"):
        s = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=16,
            pool_maxsize=16,
        )
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        s.headers.update(_HEADERS)
        _thread_local.session = s
    return _thread_local.session


# T25: implicit event_selectors defaults keyed by url_main domain pattern
_EVENT_SELECTORS_DEFAULTS: dict[str, dict[str, str]] = {
    "conf.researchr.org": {"date": "div.place", "place": "div.place a"},
    "usenix.org": {
        "date": ".field-name-field-date-text .field-item",
        "place": ".field-name-field-address-text .field-item",
    },
}


def _resolve_event_selectors(conf: dict) -> dict | None:
    """T25: resolve event_selectors — explicit block first, then URL-pattern defaults."""
    explicit = conf.get("event_selectors")
    if explicit:
        return explicit
    url_main = conf.get("url_main", conf.get("url", ""))
    for domain, defaults in _EVENT_SELECTORS_DEFAULTS.items():
        if domain in url_main:
            return defaults
    return None


def _build_cycle_selectors(conf: dict, cycle: dict) -> dict:
    """T26: build selectors for a cycle.

    New format: cycle is flat {name, discriminator(s)} — merged with top-level selectors.
    Old format (compat): cycle has nested selectors: block — used directly.
    """
    if "selectors" in cycle:
        return cycle["selectors"]
    merged = dict(conf.get("selectors", {}))
    merged.update({k: v for k, v in cycle.items() if k != "name"})
    return merged


# Generic date pattern: matches "Month DD, YYYY" with optional ordinal suffix
# Group 2 allows optional comma between month and year to handle "6 May, 2026" format
_GENERIC_DATE_RE = re.compile(
    r"([A-Z][a-z]+\.?\s+\d+\w*,?\s+\d{4})"
    r"|(\d+\w*\s+[A-Z][a-z]+\.?,?\s+\d{4})"
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
    # Strip trailing periods from month abbreviations (e.g. "Sept." → "Sep", "Mar." → "Mar")
    text = re.sub(r"\b(Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.", r"\1", text)
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
    # Strip trailing text after am/pm (e.g. ", anywhere on earth (UTC-12)")
    cleaned = re.sub(r"(\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)),.*$", r"\1", cleaned, flags=re.IGNORECASE)

    # Try formats with explicit time first
    for fmt in (
        "%B %d, %Y, %I:%M:%S %p",
        "%B %d, %Y, %I:%M:%S%p",
        "%B %d %Y, %I:%M:%S %p",
        "%B %d %Y, %I:%M:%S%p",
        "%B %d, %Y, %I:%M %p",
        "%B %d, %Y, %I:%M%p",
        "%B %d, %Y, %H:%M",
        "%B %d, %Y %H:%M",
        "%B %d %Y, %H:%M",
        "%b %d, %Y, %I:%M:%S %p",
        "%b %d, %Y, %I:%M:%S%p",
        "%b %d %Y, %I:%M:%S %p",
        "%b %d %Y, %I:%M:%S%p",
        "%b %d, %Y, %I:%M %p",
        "%b %d, %Y, %I:%M%p",
        "%b %d, %Y, %H:%M",
        "%b %d, %Y %H:%M",
        "%b %d %Y, %H:%M",
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
        "%d %B, %Y",     # 6 May, 2026 (comma after month)
        "%d %b, %Y",     # 6 May, 2026 abbreviated (comma after month)
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
    soup = BeautifulSoup(html, "lxml")

    # Remove script/style blocks
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()

    # Handle strikethrough: remove struck text only when a non-struck date
    # exists alongside it (e.g. "~03 Dec~ 10 Dec (extended!)").
    # Otherwise preserve it — past deadlines are still valid data.
    _DATE_SNIFF_RE = re.compile(
        r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\b"
        r"|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2}\b"
        r"|\b\d{4}[-/]\d{2}[-/]\d{2}\b",
        re.IGNORECASE,
    )
    for tag in soup.find_all(["s", "strike"]):
        parent = tag.parent
        if parent:
            # Check if parent has date text outside the struck element
            siblings_text = "".join(
                sib.get_text() for sib in parent.children if sib is not tag
            )
            if _DATE_SNIFF_RE.search(siblings_text):
                tag.decompose()  # superseded by non-struck date
            # else: keep struck text (it's the only date available)

    # Process <tr>: join cells with ' | ', but handle <br>-column tables specially.
    # If all cells in a <tr> have the same number of <br>-separated items (≥2),
    # emit one line per pair (CVPR-style parallel label/date columns).
    _BR_MARKER = "\x00BR\x00"

    def _cell_br_parts(cell) -> list[str]:
        """Split a cell's text by <br> boundaries using a unique in-text marker."""
        import copy
        clone = copy.copy(cell)
        for br in clone.find_all("br"):
            br.replace_with(_BR_MARKER)
        return [p.strip() for p in clone.get_text(separator="", strip=True).split(_BR_MARKER) if p.strip()]

    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        # Get <br>-split items per cell
        cell_parts = [_cell_br_parts(cell) for cell in cells]
        # Check if all cells have ≥2 items and the same count → parallel column table
        counts = [len(p) for p in cell_parts]
        if len(cells) >= 2 and min(counts) >= 2 and min(counts) == max(counts):
            lines = []
            for row_items in zip(*cell_parts):
                lines.append(" | ".join(row_items))
            tr.replace_with("\n".join(lines) + "\n")
        else:
            text = " | ".join(c.get_text(separator=" ", strip=True) for c in cells)
            tr.replace_with(text + "\n")

    # Replace <br> with space to keep remaining inline content on one line
    for br in soup.find_all("br"):
        br.replace_with(" ")

    # Process <dt>/<dd> pairs: merge onto one line
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        dt_text = dt.get_text(strip=True)
        dd_text = dd.get_text(strip=True) if dd else ""
        dt.replace_with(f"{dt_text} | {dd_text}\n")
        if dd:
            dd.decompose()

    # Process <li>: flatten leaf items; unwrap containers (nested lists)
    for li in soup.find_all("li"):
        if li.find(["ul", "ol"]):
            # List container — unwrap so nested <li> are processed individually
            li.unwrap()
        else:
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



def _extract_deadlines_researchr(
    track_slug: str, html: str, cycle_filter: str | None = None
) -> list[dict]:
    """Extract deadlines from researchr.org dates page (T20).

    Filters <tr href="...track_slug..."> rows, reads col0 (date) + col2 (label).
    cycle_filter: if set, only rows whose col2 contains this string are used
    (e.g. "First Cycle" / "Second Cycle" for ICSE multi-cycle).
    """
    soup = BeautifulSoup(html, "lxml")
    return _extract_deadlines_researchr_soup(track_slug, soup, cycle_filter)


def _extract_deadlines_researchr_soup(
    track_slug: str, soup: BeautifulSoup, cycle_filter: str | None = None
) -> list[dict]:
    """Soup-based inner implementation — reuses a pre-parsed tree.

    Collects all (date, label) pairs for the track, sorts by date ascending,
    then deduplicates keeping the earliest date per canonical label.
    """
    rows: list[tuple[str, str]] = []

    for tr in soup.find_all("tr"):
        href = tr.get("href", "")
        if track_slug not in href:
            continue
        cells = tr.find_all(["td", "th"])
        if len(cells) < 3:
            continue
        date_text = cells[0].get_text(strip=True)
        label_text = cells[2].get_text(strip=True)
        if cycle_filter and cycle_filter.lower() not in label_text.lower():
            continue
        parsed = _parse_deadline_date(date_text)
        label = _match_label(label_text)
        if parsed and label:
            rows.append((parsed, label))

    rows.sort(key=lambda x: x[0])
    seen_labels: set[str] = set()
    deadlines = []
    for parsed, label in rows:
        if label not in seen_labels:
            seen_labels.add(label)
            deadlines.append({"label": label, "date": parsed})

    return deadlines


def _autodiscover_researchr(
    html: str, cycle_filter: str | None = None, conf_prefix: str | None = None
) -> list[dict]:
    """Auto-discover best research track on a researchr.org dates page.

    Collects all unique track slugs from <tr href=...> attributes, scores each
    by (conf_prefix_match, canonical_label_count, research_or_papers_in_slug),
    returns deadlines from highest-scoring track.

    conf_prefix: lowercase conference name (e.g. "pldi") used to prefer tracks
    whose slug starts with the conference identifier over co-located workshops.

    Parses HTML exactly once and reuses the soup for all slug evaluations.
    """
    soup = BeautifulSoup(html, "lxml")
    seen_slugs: list[str] = []
    for tr in soup.find_all("tr"):
        href = tr.get("href", "")
        if not href:
            continue
        slug = href.rstrip("/").split("/")[-1]
        if slug and slug not in seen_slugs:
            seen_slugs.append(slug)

    if not seen_slugs:
        return []

    best_result: list[dict] = []
    best_score: tuple[int, int, bool] = (-1, -1, False)
    for slug in seen_slugs:
        result = _extract_deadlines_researchr_soup(slug, soup, cycle_filter)
        slug_lower = slug.lower()
        prefix_match = 1 if (conf_prefix and slug_lower.startswith(conf_prefix)) else 0
        has_papers = "research" in slug_lower or "papers" in slug_lower
        score = (prefix_match, len(result), has_papers)
        if score > best_score:
            best_score = score
            best_result = result

    return best_result


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

# Compact range: "November 6–13, 2025" or "Nov 6-13, 2025"
_DATE_RANGE_RE = re.compile(
    r"([A-Z][a-z]+\.?\s+)(\d+)\s*[–\-]\s*(\d+)(,?\s*\d{4})"
)
# Expanded range: "April 27 - April 29, 2026" (repeated month name)
_DATE_RANGE_EXPANDED_RE = re.compile(
    r"([A-Z][a-z]+\.?\s+\d+)\s*[–\-]\s*([A-Z][a-z]+\.?\s+\d+)(,?\s*\d{4})?"
)

# When a range is detected, emit label + this partner label for the end date.
_RANGE_LABEL_PAIRS: dict[str, str] = {
    "rebuttal_start": "rebuttal_end",
}


def _split_date_range(text: str) -> tuple[str, str] | None:
    """Split a date range string into (start, end) date strings.

    Format 1 — compact same-month: "November 6–13, 2025" → ("November 6, 2025", "November 13, 2025")
    Format 2 — expanded:           "April 27 - April 29, 2026" → ("April 27, 2026", "April 29, 2026")
    Returns None if text is not a recognised date range.
    """
    text = text.strip()
    # Format 1
    m = _DATE_RANGE_RE.match(text)
    if m:
        month, day1, day2, year_part = m.groups()
        month = month.strip()
        year_clean = re.sub(r"^,?\s*", ", ", year_part.strip()) if year_part.strip() else ""
        return f"{month} {day1}{year_clean}", f"{month} {day2}{year_clean}"
    # Format 2 — expanded month range
    m2 = _DATE_RANGE_EXPANDED_RE.match(text)
    if m2:
        start_raw, end_raw, year_part = m2.groups()
        start_raw, end_raw = start_raw.strip(), end_raw.strip()
        year_clean = re.sub(r"^,?\s*", ", ", year_part.strip()) if (year_part and year_part.strip()) else ""
        # Append year to end; also to start if it lacks one
        end_with_year = end_raw + year_clean if year_clean else end_raw
        start_with_year = start_raw + year_clean if (year_clean and not re.search(r"\d{4}", start_raw)) else start_raw
        return start_with_year, end_with_year
    return None


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

    # Pass 1: find all (line_index, parsed_date) tuples + range hits.
    # Range lines are excluded from proximity label search in Pass 2b.
    date_hits: list[tuple[int, str]] = []
    range_hits: list[tuple[int, str, str]] = []  # (line_idx, start_date, end_date)
    range_line_indices: set[int] = set()          # lines consumed by ranges
    for i, line in enumerate(lines):
        # Range detection takes priority: check before generic date pattern.
        # This prevents lines like "Rebuttal period | April 27 - April 29, 2026"
        # from being consumed as single-date hits (generic RE finds "April 29").
        _rm = _DATE_RANGE_RE.search(line) or _DATE_RANGE_EXPANDED_RE.search(line)
        if _rm:
            rng = _split_date_range(_rm.group(0))
            if rng:
                ps = _parse_deadline_date(rng[0])
                pe = _parse_deadline_date(rng[1])
                if ps and pe:
                    range_hits.append((i, ps, pe))
                    range_line_indices.add(i)
                    continue  # consumed as range; don't also add as date_hit

        m = _GENERIC_DATE_RE.search(line)
        if m:
            date_str = m.group(1) or m.group(2)
            tail = line[m.start():]
            parsed = _parse_deadline_date(tail) or _parse_deadline_date(date_str)
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

    # Pass 2c: resolve range hits — same-line label match ONLY (no proximity).
    # Real deadline ranges (rebuttal period) always have their label on the same line.
    # Non-deadline ranges (conference dates, workshop dates) must not steal nearby labels.
    # Only emit if label is range-appropriate (rebuttal_start); prevents CVPR-style
    # one-big-line Important Dates tables from assigning a range date to `abstract`.
    for line_idx, start_date, end_date in range_hits:
        label = _match_label(lines[line_idx])
        if label and label in _RANGE_LABEL_PAIRS and label not in seen_labels:
            seen_labels.add(label)
            deadlines.append({"label": label, "date": start_date})
            partner = _RANGE_LABEL_PAIRS.get(label)
            if partner and partner not in seen_labels:
                seen_labels.add(partner)
                deadlines.append({"label": partner, "date": end_date})

    # Pass 2b: proximity search for remaining unmatched single-date hits.
    # Skips range-hit lines as label sources to prevent label theft.
    # Also skips dates embedded in long prose (>12 words) — these are
    # incidental mentions, not structured deadline entries.
    for line_idx, parsed_date in date_hits:
        if line_idx in matched_indices:
            continue
        # Date on a long prose line is not a deadline entry
        if len(lines[line_idx].split()) > 12:
            continue
        best_label = None
        nearest_seen = False
        for dist in range(1, 3):  # ±1, ±2 lines
            if best_label or nearest_seen:
                break
            for check_idx in [line_idx - dist, line_idx + dist]:
                if 0 <= check_idx < len(lines) and check_idx not in range_line_indices:
                    candidate_line = lines[check_idx]
                    # Skip long prose lines — label keywords in running
                    # text are not actual deadline labels.
                    if len(candidate_line.split()) > 12:
                        continue
                    label = _match_label(candidate_line)
                    if label:
                        if label not in seen_labels:
                            best_label = label
                        else:
                            # Nearest label already consumed — this date is
                            # a duplicate of an already-matched deadline.
                            nearest_seen = True
                        break
        if best_label:
            seen_labels.add(best_label)
            deadlines.append({"label": best_label, "date": parsed_date})

    return deadlines


def _fetch(url: str) -> str:
    resp = _get_session().get(url, timeout=30)
    resp.encoding = resp.apparent_encoding
    return resp.text


# Phrases that indicate a page is a placeholder without real CFP content yet.
_SCAFFOLDING_PHRASES: frozenset[str] = frozenset([
    "coming soon",
    "under construction",
    "will be announced soon",
    "to be announced soon",
    "stay tuned",
    "check back later",
    "page not found",
    "404 not found",
    "website not found",
    "site not found",
])

# Pages with fewer words than this (after HTML stripping) are likely placeholders.
_MIN_CONTENT_WORDS = 75


def _check_date_year_sanity(deadlines: list[dict], year: int, name: str, url: str) -> None:
    """Raise ValueError if all extracted dates are stale (>1 year before target year).

    Catches pages that exist but show historical CFP data (e.g. PODC 2027 page
    showing 2018 deadlines). Only fires when deadlines are non-empty — an empty
    list is handled elsewhere.
    """
    if not deadlines:
        return
    date_years = []
    for d in deadlines:
        raw = d.get("date", "")
        if raw and len(raw) >= 4 and raw[:4].isdigit():
            date_years.append(int(raw[:4]))
    if not date_years:
        return
    if max(date_years) < year - 1:
        raise ValueError(
            f"{name}: stale CFP detected — extracted dates are from {max(date_years)}"
            f" but target year is {year} (url: {url})"
        )


def _is_scaffolding(html: str) -> bool:
    """Return True if page is a placeholder/scaffolding with no real CFP content.

    Three signals:
    - Phrase match: known placeholder phrases in the stripped text.
    - Leading 404: stripped text starts with "404" — CMS 404 pages that don't
      include "not found" verbatim (e.g. "404 - ConferenceName ...").
    - Word count: fewer than _MIN_CONTENT_WORDS words AND no date patterns found
      (a sparse page with real dates is a terse CFP, not scaffolding).
    """
    text = _strip_html(html)
    lower = text.lower()
    if any(phrase in lower for phrase in _SCAFFOLDING_PHRASES):
        return True
    if re.match(r"^\s*404\b", text):
        return True
    if len(text.split()) < _MIN_CONTENT_WORDS:
        return not bool(_GENERIC_DATE_RE.search(text))
    return False


class RegexStrategy(BaseStrategy):
    name = "regex"

    def extract(self, conf: dict, year: int) -> list[CrawlResult]:
        url = resolve_url(conf, year)
        if not url:
            raise ValueError(f"{conf['name']}: no URL configured")

        html = _fetch(url)

        if _is_scaffolding(html):
            raise ValueError(f"{conf['name']}: scaffolding/placeholder page detected at {url}")

        # Shared fields from main page
        date, place = self._extract_main_fields(conf, year, url, html)

        no_specific = conf.get("_no_specific", False)
        conf_prefix = conf["name"].lower()
        cycles = conf.get("cycles")
        if cycles:
            # One CrawlResult per cycle
            results = []
            for cycle in cycles:
                deadlines = self._extract_deadlines(_build_cycle_selectors(conf, cycle), html, year, no_specific=no_specific, conf_prefix=conf_prefix)
                _check_date_year_sanity(deadlines, year, conf["name"], url)
                results.append(CrawlResult(
                    name=conf["name"],
                    year=year,
                    link=url,
                    deadlines=deadlines,
                    cycle=cycle.get("name"),
                    date=date,
                    place=place,
                    description=conf.get("description"),
                    tags=list(conf.get("tags", [])),
                ))
            return results
        else:
            # No cycles — single result using top-level selectors
            deadlines = self._extract_deadlines(conf.get("selectors", {}), html, year, no_specific=no_specific, conf_prefix=conf_prefix)
            _check_date_year_sanity(deadlines, year, conf["name"], url)
            return [CrawlResult(
                name=conf["name"],
                year=year,
                link=url,
                deadlines=deadlines,
                date=date,
                place=place,
                description=conf.get("description"),
                tags=list(conf.get("tags", [])),
            )]

    def _extract_main_fields(
        self, conf: dict, year: int, cfp_url: str, cfp_html: str
    ) -> tuple[str | None, str | None]:
        event_selectors = _resolve_event_selectors(conf)
        # Static fallback: date/place can be hardcoded in conf (e.g. via by_year)
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
        # Strip trailing place text from date if both share same parent element
        # (e.g. researchr "div.place" has date text + <a>place</a>)
        if date and place and date.endswith(place):
            date = date[: -len(place)].strip()
        return date, place

    @staticmethod
    def _extract_deadlines(selectors: dict, html: str, year: int | None = None, no_specific: bool = False, conf_prefix: str | None = None) -> list[dict]:
        # Optionally narrow HTML to a section first
        section_pattern = selectors.get("section")
        if section_pattern:
            m = re.search(section_pattern, html, re.DOTALL | re.IGNORECASE)
            if m:
                html = m.group(0)
            else:
                return []

        # Fallback chain: researchr_track → researchr auto-discover → site-specific → generic
        cycle_filter = selectors.get("researchr_cycle")
        track_slug = selectors.get("researchr_track")
        if track_slug:
            if year:
                track_slug = track_slug.replace("{YYYY}", str(year))
            result = _extract_deadlines_researchr(track_slug, html, cycle_filter)
            if result:
                return result
        else:
            result = _autodiscover_researchr(html, cycle_filter, conf_prefix=conf_prefix)
            if result:
                return result

        deadline_specs = selectors.get("deadlines", [])
        if deadline_specs and not no_specific:
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
