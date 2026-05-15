"""CORE 2026 conference ranking lookup from downloaded CSV."""

import csv
import io
from pathlib import Path

_VALID_RANKS = {"A*", "A", "B", "C"}
_DEFAULT_CSV = Path(__file__).parent.parent / "data" / "core2026.csv"


def load_ranks(csv_path: Path | str = _DEFAULT_CSV) -> dict[str, str]:
    """Load CORE rankings CSV. Returns {acronym_lower: rank}.

    First match wins on duplicate acronyms (CSV is sorted by title, so
    e.g. "ACM FSE" (A*) beats "Fast Software Encryption FSE" (B)).
    Returns empty dict if CSV not found.
    """
    path = Path(csv_path)
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    ranks: dict[str, str] = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) >= 5:
            acronym = row[2].strip()
            rank = row[4].strip()
            if acronym and acronym.lower() not in ranks:
                ranks[acronym.lower()] = rank
    return ranks


def lookup(acronym: str, ranks: dict[str, str]) -> str | None:
    """Return CORE rank for acronym, or None if not found."""
    return ranks.get(acronym.lower())
