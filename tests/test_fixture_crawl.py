"""Integration tests using saved HTML fixtures instead of live HTTP.

Patches crawler.compat._fetch to load from tests/fixtures/{slug}_{year}.html
(and _main.html).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from crawler.config import load_conferences, resolve_conf_for_year, resolve_url
from crawler.compat import crawl_conference

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"

CANONICAL_LABELS = {
    "abstract",
    "submission",
    "early_reject",
    "rebuttal_start",
    "rebuttal_end",
    "notification",
    "shepherd",
    "camera_ready",
}

# Load all conferences once at module level
_CONFS: dict[str, dict] = {conf["name"]: conf for conf in load_conferences()}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slug(name: str) -> str:
    """Slug: lowercase, non-alphanumeric → hyphen, strip edges."""
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _build_url_map(conf: dict, year: int) -> dict[str, Path]:
    """Map resolved URLs → fixture Path objects for this conf+year."""
    slug = _slug(conf["name"])
    url_map: dict[str, Path] = {}

    resolved = resolve_conf_for_year(conf, year)
    if resolved is None:
        return url_map

    cfp_url = resolve_url(resolved, year)
    if cfp_url:
        p = FIXTURES_DIR / f"{slug}_{year}.html"
        if p.exists():
            url_map[cfp_url] = p

    url_main_tmpl = resolved.get("url_main")
    if url_main_tmpl:
        main_url = resolve_url({"url": url_main_tmpl}, year)
        if main_url and main_url != cfp_url:
            p = FIXTURES_DIR / f"{slug}_{year}_main.html"
            if p.exists():
                url_map[main_url] = p

    return url_map


def _make_fetch(url_map: dict[str, Path]):
    """Return a _fetch function that reads from fixture files."""
    def _fixture_fetch(url: str) -> str:
        if url in url_map:
            return url_map[url].read_text(encoding="utf-8")
        raise FileNotFoundError(
            f"No fixture for URL: {url}\n"
            f"Known URLs: {list(url_map.keys())}"
        )
    return _fixture_fetch


def _install_fixture_fetch(monkeypatch, conf_name: str, year: int) -> None:
    """Install fixture-backed _fetch into compat module."""
    conf = _CONFS[conf_name]
    url_map = _build_url_map(conf, year)
    fn = _make_fetch(url_map)
    monkeypatch.setattr("crawler.compat._fetch", fn)


def _get_all_deadlines(conf_name: str, year: int) -> list[dict]:
    """Return flat list of all deadline dicts across all results."""
    conf = _CONFS[conf_name]
    results = crawl_conference(conf, year)
    return [dl for r in results for dl in r.deadlines]


# ---------------------------------------------------------------------------
# Parametrize data
# ---------------------------------------------------------------------------

# All (conf_name, year) pairs from ground truth — used for format validation.
ALL_PAIRS: list[tuple[str, int]] = [
    # 2026
    ("USENIX Security", 2026),
    ("IEEE S&P", 2026),
    ("ACM CCS", 2026),
    ("NDSS", 2026),
    ("ACSAC", 2026),
    ("RAID", 2026),
    ("IEEE EuroS&P", 2026),
    ("ASIACCS", 2026),
    ("PoPETs", 2026),
    ("DIMVA", 2026),
    ("SOSP", 2026),
    ("OSDI", 2026),
    ("EuroSys", 2026),
    ("ASPLOS", 2026),
    ("ATC", 2026),
    ("NSDI", 2026),
    ("SIGCOMM", 2026),
    ("FAST", 2026),
    ("IMC", 2026),
    ("ASE", 2026),
    ("FSE", 2026),
    ("ISSTA", 2026),
    ("ICSE", 2026),
    ("PLDI", 2026),
    ("POPL", 2026),
    ("ICFP", 2026),
    ("OOPSLA", 2026),
    ("ECOOP", 2026),
    ("ISCA", 2026),
    ("MICRO", 2026),
    ("HPCA", 2026),
    ("DAC", 2026),
    ("ICSME", 2026),
    ("SANER", 2026),
    ("ICPC", 2026),
    ("SCAM", 2026),
    ("ICST", 2026),
    # 2025
    ("IEEE S&P", 2025),
    ("RAID", 2025),
    ("ASIACCS", 2025),
    ("ACSAC", 2025),
    ("PoPETs", 2025),
    ("DIMVA", 2025),
    ("EuroSys", 2025),
    ("OSDI", 2025),
    ("SIGCOMM", 2025),
    ("NSDI", 2025),
    ("IMC", 2025),
    ("HotOS", 2025),
    ("FSE", 2025),
    ("ASE", 2025),
    ("ISSTA", 2025),
    ("ICSME", 2025),
    ("SANER", 2025),
    ("ICPC", 2025),
    ("SCAM", 2025),
    ("PLDI", 2025),
    ("ICSE", 2025),
    ("POPL", 2025),
    ("ISCA", 2025),
    ("MICRO", 2025),
    ("ECOOP", 2025),
    ("ICFP", 2025),
    ("OOPSLA", 2025),
    # 2027
    ("USENIX Security", 2027),
    ("IEEE S&P", 2027),
    ("PoPETs", 2027),
    ("EuroSys", 2027),
    ("ASPLOS", 2027),
    ("NSDI", 2027),
    ("FAST", 2027),
    ("FSE", 2027),
    ("ICSE", 2027),
    ("POPL", 2027),
]

# Subset: (conf_name, year, required_labels)
REQUIRED_LABELS_CASES: list[tuple[str, int, frozenset[str]]] = [
    ("USENIX Security", 2026, frozenset({"abstract", "submission", "early_reject",
                                          "rebuttal_start", "rebuttal_end",
                                          "notification", "shepherd", "camera_ready"})),
    ("IEEE S&P", 2026, frozenset({"abstract", "submission", "early_reject", "notification"})),
    ("ACM CCS", 2026, frozenset({"abstract", "submission", "early_reject",
                                  "notification", "shepherd", "camera_ready"})),
    ("NDSS", 2026, frozenset({"submission", "early_reject", "notification",
                               "shepherd", "camera_ready"})),
    ("ACSAC", 2026, frozenset({"submission", "early_reject", "rebuttal_start",
                                "notification", "shepherd", "camera_ready"})),
    ("RAID", 2026, frozenset({"submission", "notification", "camera_ready"})),
    ("IEEE EuroS&P", 2026, frozenset({"submission", "early_reject", "notification", "camera_ready"})),
    ("ASIACCS", 2026, frozenset({"submission", "early_reject", "notification", "camera_ready"})),
    ("PoPETs", 2026, frozenset({"submission", "notification", "shepherd", "camera_ready"})),
    ("DIMVA", 2026, frozenset({"submission", "notification"})),
    ("SOSP", 2026, frozenset({"abstract", "submission", "rebuttal_start",
                               "rebuttal_end", "notification", "camera_ready"})),
    ("OSDI", 2026, frozenset({"abstract", "submission", "notification", "camera_ready"})),
    ("ATC", 2026, frozenset({"submission", "early_reject", "rebuttal_start",
                              "rebuttal_end", "notification", "camera_ready"})),
    ("SIGCOMM", 2026, frozenset({"abstract", "submission", "notification",
                                  "shepherd", "camera_ready", "rebuttal_start", "rebuttal_end"})),
    ("ASE", 2026, frozenset({"submission", "early_reject", "notification", "camera_ready"})),
    ("FSE", 2026, frozenset({"abstract", "submission", "notification", "camera_ready"})),
    ("ISSTA", 2026, frozenset({"submission", "notification", "camera_ready"})),
    ("PLDI", 2026, frozenset({"submission", "notification", "camera_ready"})),
    ("POPL", 2026, frozenset({"submission", "rebuttal_start", "shepherd", "notification", "camera_ready"})),
    ("ICFP", 2026, frozenset({"submission", "notification", "camera_ready"})),
    ("ISCA", 2026, frozenset({"abstract", "submission", "notification",
                               "rebuttal_start", "rebuttal_end"})),
    ("MICRO", 2026, frozenset({"abstract", "submission", "notification", "camera_ready",
                                "rebuttal_start", "rebuttal_end"})),
    ("HPCA", 2026, frozenset({"abstract", "submission", "notification", "camera_ready",
                               "rebuttal_start", "rebuttal_end"})),
    ("DAC", 2026, frozenset({"abstract", "submission", "notification", "camera_ready"})),
    ("ICSME", 2026, frozenset({"abstract", "submission", "notification"})),
    ("SANER", 2026, frozenset({"abstract", "submission", "notification", "camera_ready"})),
    ("ICPC", 2026, frozenset({"abstract", "submission", "notification", "camera_ready"})),
    ("SCAM", 2026, frozenset({"submission", "notification", "camera_ready"})),
    ("ICST", 2026, frozenset({"submission", "notification", "camera_ready"})),
    # 2025 subset
    ("IEEE S&P", 2025, frozenset({"submission", "notification"})),
    ("RAID", 2025, frozenset({"submission", "notification", "camera_ready"})),
    ("ACSAC", 2025, frozenset({"submission", "early_reject", "rebuttal_start",
                                "notification", "shepherd", "camera_ready"})),
    ("OSDI", 2025, frozenset({"abstract", "submission", "rebuttal_start",
                               "rebuttal_end", "notification", "camera_ready"})),
    ("SIGCOMM", 2025, frozenset({"abstract", "submission", "notification",
                                  "shepherd", "camera_ready"})),
    ("HotOS", 2025, frozenset({"submission", "notification", "camera_ready"})),
    ("FSE", 2025, frozenset({"submission", "notification", "camera_ready"})),
    ("PLDI", 2025, frozenset({"submission", "notification", "camera_ready"})),
    ("POPL", 2025, frozenset({"submission", "rebuttal_start", "shepherd",
                               "notification", "camera_ready"})),
    ("ISCA", 2025, frozenset({"abstract", "submission", "notification",
                               "rebuttal_start", "rebuttal_end"})),
    ("ICFP", 2025, frozenset({"submission", "shepherd", "notification", "camera_ready"})),
    # 2027 subset
    ("USENIX Security", 2027, frozenset({"abstract", "submission"})),
    ("IEEE S&P", 2027, frozenset({"abstract", "submission", "early_reject",
                                   "notification", "camera_ready"})),
    ("FSE", 2027, frozenset({"submission", "notification"})),
    ("ICSE", 2027, frozenset({"abstract", "submission", "rebuttal_start",
                               "notification", "camera_ready"})),
    ("POPL", 2027, frozenset({"submission", "notification", "shepherd", "camera_ready"})),
]

# Subset: (conf_name, year, expected_submission_date)
SUBMISSION_DATE_CASES: list[tuple[str, int, str]] = [
    # 2026
    ("USENIX Security", 2026, "2025-08-26 23:59"),   # cycle 1
    ("USENIX Security", 2026, "2026-02-05 23:59"),   # cycle 2 — same param id, separate entries
    ("IEEE S&P", 2026, "2025-06-05 23:59"),           # cycle 1
    ("IEEE S&P", 2026, "2025-11-13 23:59"),           # cycle 2
    ("ACM CCS", 2026, "2026-01-14 23:59"),            # cycle A
    ("ACM CCS", 2026, "2026-04-29 23:59"),            # cycle B
    ("NDSS", 2026, "2025-04-23 23:59"),               # summer
    ("NDSS", 2026, "2025-08-06 23:59"),               # fall
    ("ACSAC", 2026, "2026-05-26 23:59"),
    ("RAID", 2026, "2026-04-16 23:59"),
    ("IEEE EuroS&P", 2026, "2025-11-20 23:59"),
    ("ASIACCS", 2026, "2025-08-25 23:59"),            # cycle 1
    ("ASIACCS", 2026, "2025-12-12 23:59"),            # cycle 2
    ("DIMVA", 2026, "2025-12-10 23:59"),              # cycle 1
    ("SOSP", 2026, "2026-04-01 23:59"),
    ("OSDI", 2026, "2025-12-11 17:59"),
    ("ATC", 2026, "2026-06-10 23:59"),
    ("SIGCOMM", 2026, "2026-02-06 23:59"),
    ("ASE", 2026, "2026-03-26 23:59"),
    ("FSE", 2026, "2025-09-11 23:59"),
    ("ISSTA", 2026, "2026-01-29 23:59"),
    ("PLDI", 2026, "2025-11-13 23:59"),
    ("POPL", 2026, "2025-07-10 23:59"),
    ("ICFP", 2026, "2026-02-19 23:59"),
    ("ISCA", 2026, "2025-11-17 23:59"),
    ("MICRO", 2026, "2026-04-07 23:59"),
    ("HPCA", 2026, "2025-08-01 23:59"),
    ("DAC", 2026, "2025-11-19 23:59"),
    ("ICSME", 2026, "2026-03-06 23:59"),
    ("SANER", 2026, "2025-11-17 23:59"),
    ("ICPC", 2026, "2025-10-23 23:59"),
    ("SCAM", 2026, "2026-06-11 23:59"),
    ("ICST", 2026, "2026-02-20 23:59"),
    # 2025
    ("IEEE S&P", 2025, "2024-06-06 23:59"),           # cycle 1
    ("IEEE S&P", 2025, "2024-11-14 23:59"),           # cycle 2
    ("RAID", 2025, "2025-04-24 23:59"),
    ("ASIACCS", 2025, "2024-09-20 23:59"),            # cycle 1
    ("ACSAC", 2025, "2025-05-30 23:59"),
    ("OSDI", 2025, "2024-12-10 17:59"),
    ("SIGCOMM", 2025, "2025-01-31 23:59"),
    ("HotOS", 2025, "2025-01-15 23:59"),
    ("FSE", 2025, "2024-09-12 23:59"),     # research papers track
    ("ASE", 2025, "2025-05-30 23:59"),
    ("ISSTA", 2025, "2024-10-31 23:59"),
    ("ICSME", 2025, "2025-03-13 23:59"),
    ("SANER", 2025, "2024-10-13 23:59"),
    ("ICPC", 2025, "2024-11-09 23:59"),
    ("SCAM", 2025, "2025-06-09 23:59"),
    ("PLDI", 2025, "2024-11-14 23:59"),
    ("POPL", 2025, "2024-07-11 23:59"),
    ("ISCA", 2025, "2024-11-22 23:59"),
    ("MICRO", 2025, "2025-04-11 23:59"),
    ("ICFP", 2025, "2025-02-27 23:59"),
    # 2027
    ("USENIX Security", 2027, "2026-08-25 23:59"),     # cycle 1
    ("USENIX Security", 2027, "2027-01-26 23:59"),     # cycle 2
    ("IEEE S&P", 2027, "2026-06-11 23:59"),           # cycle 1
    ("FSE", 2027, "2026-10-02 23:59"),
    ("ICSE", 2027, "2026-06-30 23:59"),
    ("POPL", 2027, "2026-07-09 23:59"),
]


# ---------------------------------------------------------------------------
# Build pytest.param lists with readable IDs
# ---------------------------------------------------------------------------

def _pair_id(conf_name: str, year: int) -> str:
    return f"{_slug(conf_name)}-{year}"


def _sub_id(conf_name: str, year: int, extra: str) -> str:
    safe = extra.replace(" ", "-").replace(":", "")
    return f"{_slug(conf_name)}-{year}-{safe}"


ALL_PAIRS_PARAMS = [
    pytest.param(conf_name, year, id=_pair_id(conf_name, year))
    for conf_name, year in ALL_PAIRS
]

REQUIRED_LABELS_PARAMS = [
    pytest.param(conf_name, year, required_labels, id=_pair_id(conf_name, year))
    for conf_name, year, required_labels in REQUIRED_LABELS_CASES
]

SUBMISSION_DATE_PARAMS = [
    pytest.param(conf_name, year, expected_sub,
                 id=_sub_id(conf_name, year, expected_sub))
    for conf_name, year, expected_sub in SUBMISSION_DATE_CASES
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("conf_name,year", ALL_PAIRS_PARAMS)
def test_deadline_format_valid(conf_name: str, year: int, monkeypatch):
    """All extracted deadlines must have valid format and canonical labels."""
    _install_fixture_fetch(monkeypatch, conf_name, year)

    conf = _CONFS[conf_name]
    results = crawl_conference(conf, year)

    assert results, f"{conf_name} {year}: expected non-empty results"

    date_re = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
    for result in results:
        for dl in result.deadlines:
            label = dl["label"]
            date = dl["date"]
            assert label in CANONICAL_LABELS, (
                f"{conf_name} {year} (cycle={result.cycle!r}): "
                f"non-canonical label {label!r}"
            )
            assert date_re.match(date), (
                f"{conf_name} {year} (cycle={result.cycle!r}): "
                f"label={label!r} date {date!r} does not match YYYY-MM-DD HH:MM"
            )


@pytest.mark.parametrize("conf_name,year,required_labels", REQUIRED_LABELS_PARAMS)
def test_required_labels_present(
    conf_name: str, year: int, required_labels: frozenset[str], monkeypatch
):
    """Required labels must appear across all cycles for this conf+year."""
    _install_fixture_fetch(monkeypatch, conf_name, year)

    conf = _CONFS[conf_name]
    results = crawl_conference(conf, year)

    assert results, f"{conf_name} {year}: expected non-empty results"

    found_labels = {dl["label"] for r in results for dl in r.deadlines}
    missing = required_labels - found_labels
    assert not missing, (
        f"{conf_name} {year}: missing required labels {missing!r}; "
        f"found: {found_labels!r}"
    )


@pytest.mark.parametrize("conf_name,year,expected_sub", SUBMISSION_DATE_PARAMS)
def test_submission_date(
    conf_name: str, year: int, expected_sub: str, monkeypatch
):
    """The expected submission date must appear in at least one result's deadlines."""
    _install_fixture_fetch(monkeypatch, conf_name, year)

    conf = _CONFS[conf_name]
    results = crawl_conference(conf, year)

    assert results, f"{conf_name} {year}: expected non-empty results"

    all_dates = {
        dl["date"]
        for r in results
        for dl in r.deadlines
        if dl["label"] == "submission"
    }
    assert expected_sub in all_dates, (
        f"{conf_name} {year}: submission date {expected_sub!r} not found; "
        f"submission dates found: {sorted(all_dates)!r}"
    )
