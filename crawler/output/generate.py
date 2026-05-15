"""Generate deadline output from crawl results or data.yaml.

Supports JSON and YAML output formats.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml
from rich.console import Console

_stderr = Console(stderr=True)


def write_yaml(data: dict, output_path: str | Path) -> None:
    """Write data dict as YAML."""
    output_path = Path(output_path)
    with open(output_path, "w") as f:
        yaml.dump(
            data, f, default_flow_style=False, allow_unicode=True, sort_keys=False
        )


def write_json(data: dict, output_path: str | Path) -> None:
    """Write data dict as formatted JSON."""
    output_path = Path(output_path)
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


WRITERS = {
    "json": write_json,
    "yaml": write_yaml,
}
FORMATS = set(WRITERS)


def _slugify(name: str) -> str:
    """Convert conference name to URL-friendly slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def _is_passed(deadline_str: str, now: datetime) -> bool:
    """Check if a deadline string (V2 format) is in the past."""
    dt = datetime.strptime(deadline_str, "%Y-%m-%d %H:%M")
    return dt < now.replace(tzinfo=None)


VALID_LABELS = {
    "abstract", "submission", "early_reject", "rebuttal_start",
    "rebuttal_end", "notification", "shepherd", "camera_ready",
}

# V14: canonical chronological order for deadline labels
LABEL_ORDER = [
    "abstract", "submission", "early_reject", "rebuttal_start",
    "rebuttal_end", "notification", "shepherd", "camera_ready",
]


def _validate_entry(entry: dict) -> list[str]:
    """Validate data.yaml entry against V1, V2, V3, V10. Return list of errors."""
    errors = []
    for field in ("name", "year", "link"):
        if not entry.get(field):
            errors.append(f"missing {field}")

    deadlines = entry.get("deadline", [])
    if not deadlines:
        errors.append("missing deadline (need ≥1)")
    for d in deadlines:
        if not isinstance(d, dict):
            errors.append(f"deadline must be dict, got: {d}")
            continue
        date_val = d.get("date", "")
        if not re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", str(date_val)):
            errors.append(f"bad deadline date format: {date_val}")
        label = d.get("label", "")
        if label not in VALID_LABELS:
            errors.append(f"bad deadline label: {label}")

    tags = entry.get("tags", [])
    if len(tags) < 2:
        errors.append("tags need ≥2 elements (area + tier)")
    else:
        if tags[0] not in {"SEC", "SYS", "HW", "SE", "PL", "GEN"}:
            errors.append(f"bad area code: {tags[0]}")
        if tags[1] not in {"TIER1", "TIER2"}:
            errors.append(f"bad tier: {tags[1]}")

    return errors


def _check_date_order(entry: dict) -> list[str]:
    """V14: check deadline dates follow canonical label sequence. Return warnings."""
    deadlines = entry.get("deadline", [])
    label_to_date = {}
    for d in deadlines:
        if isinstance(d, dict) and d.get("label") and d.get("date"):
            label_to_date[d["label"]] = d["date"]

    # Filter to labels present, in canonical order
    ordered = [(l, label_to_date[l]) for l in LABEL_ORDER if l in label_to_date]
    warnings = []
    for i in range(len(ordered) - 1):
        l1, d1 = ordered[i]
        l2, d2 = ordered[i + 1]
        if d1 > d2:
            warnings.append(f"date order: {l1} ({d1}) > {l2} ({d2})")
    return warnings


def transform_entry(entry: dict, now: datetime) -> dict:
    """Transform a single data.yaml entry to output shape."""
    tags = entry.get("tags", [])
    deadlines = entry.get("deadline", [])

    out_deadlines = []
    for d in deadlines:
        out_deadlines.append(
            {
                "label": d["label"],
                "date": d["date"],
                "passed": _is_passed(d["date"], now),
            }
        )

    return {
        "id": _slugify(f"{entry['name']} {entry['year']}" + (f" {entry['cycle']}" if entry.get("cycle") else "")),
        "name": f"{entry['name']} {entry['year']}" + (f" ({entry['cycle']})" if entry.get("cycle") else ""),
        "year": entry["year"],
        "description": entry.get("description", ""),
        "link": entry["link"],
        "area": tags[0] if tags else "",
        "tier": tags[1] if len(tags) > 1 else "",
        "place": entry.get("place") or "",
        "date": entry.get("date") or "",
        "timezone": entry.get("timezone", "AoE"),
        "deadlines": out_deadlines,
        "tags": tags,
        **({"comment": entry["comment"]} if entry.get("comment") else {}),
    }


def _result_to_entry(r) -> dict:
    """Convert a CrawlResult to a data.yaml-shaped dict."""
    entry = {
        "name": r.name,
        "cycle": r.cycle,
        "year": r.year,
        "link": r.link,
        "deadline": r.deadlines,
        "tags": r.tags,
    }
    if r.description:
        entry["description"] = r.description
    if r.date:
        entry["date"] = r.date
    if r.place:
        entry["place"] = r.place
    if r.notification:
        entry["notification"] = r.notification
    if r.timezone:
        entry["timezone"] = r.timezone
    if r.comment:
        entry["comment"] = r.comment
    return entry


def generate_from_results(
    results: list,
    output_path: str | Path | None = None,
    fmt: str = "json",
    now: datetime | None = None,
) -> dict:
    """Generate output directly from CrawlResult list. Skip invalid entries with warning."""
    if fmt not in FORMATS:
        raise ValueError(f"Unsupported format '{fmt}', must be one of {FORMATS}")

    if output_path is None:
        output_path = f"output/deadlines.{fmt}"

    if now is None:
        now = datetime.now(timezone.utc)

    conferences = []
    for r in results:
        entry = _result_to_entry(r)
        errors = _validate_entry(entry)
        if errors:
            _stderr.print(f"  [bold red]⚠ skipping[/] {entry.get('name', '?')}: {'; '.join(errors)}")
            continue
        # V14: warn on date order violations
        date_warnings = _check_date_order(entry)
        if date_warnings:
            name = entry.get("name", "?")
            for w in date_warnings:
                _stderr.print(f"  [bold yellow]⚠[/] {name}: {w}")
        conferences.append(transform_entry(entry, now))

    result = {
        "generated_at": now.isoformat(),
        "conferences": conferences,
    }

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    WRITERS[fmt](result, output_path)

    return result


def generate_output(
    data_path: str | Path = "data.yaml",
    output_path: str | Path | None = None,
    fmt: str = "json",
    now: datetime | None = None,
) -> dict:
    """Read data.yaml, validate, transform, write to file.

    Args:
        data_path: Path to data.yaml input.
        output_path: Output file path. Defaults to output/deadlines.{fmt}.
        fmt: Output format — "json" or "yaml".
        now: Reference time for passed computation. Defaults to UTC now.
    """
    if fmt not in FORMATS:
        raise ValueError(f"Unsupported format '{fmt}', must be one of {FORMATS}")

    if output_path is None:
        output_path = f"output/deadlines.{fmt}"

    data_path = Path(data_path)
    if not data_path.exists():
        raise FileNotFoundError(f"data.yaml not found: {data_path}")

    with open(data_path) as f:
        entries = yaml.safe_load(f)

    if not isinstance(entries, list):
        raise ValueError("data.yaml must be a YAML list")

    if now is None:
        now = datetime.now(timezone.utc)

    conferences = []
    for entry in entries:
        errors = _validate_entry(entry)
        if errors:
            name = entry.get("name", "?")
            raise ValueError(f"Invalid entry '{name}': {'; '.join(errors)}")
        conferences.append(transform_entry(entry, now))

    result = {
        "generated_at": now.isoformat(),
        "conferences": conferences,
    }

    WRITERS[fmt](result, output_path)

    return result
