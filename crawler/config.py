"""Load and validate conferences.yaml (I.conf)."""

import yaml
from pathlib import Path

VALID_STRATEGIES = {"css", "regex", "llm", "static"}
REQUIRED_FIELDS = {"name", "strategy", "tags"}


class ConfigError(Exception):
    pass


def load_conferences(path: str | Path = "conferences.yaml") -> list[dict]:
    """Load conferences.yaml and validate each entry against V7/V8."""
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")

    with open(path) as f:
        entries = yaml.safe_load(f)

    if not isinstance(entries, list):
        raise ConfigError("conferences.yaml must be a YAML list")

    validated = []
    for i, entry in enumerate(entries):
        _validate_entry(entry, i)
        validated.append(entry)

    return validated


def _validate_entry(entry: dict, index: int) -> None:
    """Validate a single conference entry (V7, V8)."""
    if not isinstance(entry, dict):
        raise ConfigError(f"Entry {index}: must be a mapping, got {type(entry).__name__}")

    # V7: required fields — url not required if by_year present
    missing = REQUIRED_FIELDS - set(entry.keys())
    if missing:
        raise ConfigError(
            f"Entry {index} ({entry.get('name', '?')}): missing required fields: {missing}"
        )

    if "url" not in entry and "by_year" not in entry:
        raise ConfigError(
            f"Entry {index} ({entry.get('name', '?')}): must have 'url' or 'by_year'"
        )

    # V8: strategy must be valid
    strategy = entry["strategy"]
    if strategy not in VALID_STRATEGIES:
        raise ConfigError(
            f"Entry {index} ({entry['name']}): invalid strategy '{strategy}', "
            f"must be one of {VALID_STRATEGIES}"
        )


def resolve_conf_for_year(entry: dict, year: int) -> dict | None:
    """Merge by_year overrides into conf for target year (V13).

    Returns merged conf dict, or None if year cannot be resolved
    (year not in by_year and url has no template placeholders).
    """
    by_year = entry.get("by_year")
    if not by_year:
        return entry

    year_conf = by_year.get(year)
    if year_conf:
        # Merge: year-specific fields override top-level
        merged = dict(entry)
        merged.pop("by_year", None)
        merged.update(year_conf)
        return merged

    # Year not in by_year — fall back to top-level url if it has placeholders
    url = entry.get("url", "")
    if "{YYYY}" in url or "{YY}" in url:
        return entry

    # No template, no year entry → skip
    return None


def resolve_url(entry: dict, year: int) -> str | None:
    """Resolve {YYYY}/{YY} placeholders in conference URL."""
    url = entry.get("url")
    if url is None:
        return None
    return url.replace("{YYYY}", str(year)).replace("{YY}", str(year % 100))
