"""CLI entry point for deadline-crawler."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from crawler.strategy import crawl_all
from crawler.output.generate import generate_from_results, _validate_entry


def _parse_years(raw: str | None) -> list[int] | None:
    """Parse comma-separated year string into list of ints."""
    if raw is None:
        return None
    return [int(y.strip()) for y in raw.split(",")]


def cmd_crawl(args):
    """Crawl conferences and export output."""
    years = _parse_years(args.year)

    try:
        results = crawl_all(
            config_path=args.config,
            years=years,
            name_filter=args.conf,
            workers=args.workers,
        )
    except Exception as e:
        print(f"Crawl failed: {e}", file=sys.stderr)
        sys.exit(1)

    if not results:
        print("No results.")
        return

    output = generate_from_results(
        results,
        output_path=args.output,
        fmt=args.format,
    )

    n = len(output["conferences"])
    out_path = args.output or f"output/deadlines.{args.format}"
    print(f"\nExported {n} conference(s) → {out_path}")


# --- T10: validate command ---


def _load_output_file(path: str) -> dict:
    """Load exported deadlines file (JSON or YAML)."""
    p = Path(path)
    if not p.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(p) as f:
        if p.suffix == ".json":
            return json.load(f)
        else:
            import yaml
            return yaml.safe_load(f)


def _output_to_entry(conf: dict) -> dict:
    """Convert output-shaped conference back to entry shape for validation."""
    return {
        "name": conf.get("name", ""),
        "year": conf.get("year", ""),
        "link": conf.get("link", ""),
        "deadline": [
            {"label": d["label"], "date": d["date"]}
            for d in conf.get("deadlines", [])
        ],
        "tags": conf.get("tags", []),
    }


def cmd_validate(args):
    """Validate exported output against invariants V1-V4, V10."""
    data = _load_output_file(args.input)
    conferences = data.get("conferences", [])

    if not conferences:
        print("No conferences found in file.")
        return

    seen = set()
    total_errors = 0

    for conf in conferences:
        entry = _output_to_entry(conf)
        errors = _validate_entry(entry)

        # V4: duplicate check
        key = (conf.get("name"), conf.get("year"))
        if key in seen:
            errors.append(f"duplicate (name, year): {key}")
        seen.add(key)

        if errors:
            total_errors += len(errors)
            print(f"✗ {conf.get('name', '?')} ({conf.get('year', '?')}):")
            for e in errors:
                print(f"    {e}")

    if total_errors == 0:
        print(f"✓ {len(conferences)} conference(s) valid.")
    else:
        print(f"\n{total_errors} error(s) in {len(conferences)} conference(s).")
        sys.exit(1)


# --- T11: terminal table with color ---

# ANSI color codes
_RED = "\033[31m"
_YELLOW = "\033[33m"
_GREEN = "\033[32m"
_RESET = "\033[0m"
_BOLD = "\033[1m"


def _days_until(deadline_str: str, now: datetime) -> int | None:
    """Days until deadline. Negative = past."""
    try:
        dt = datetime.strptime(deadline_str, "%Y-%m-%d %H:%M")
        delta = dt - now.replace(tzinfo=None)
        return delta.days
    except ValueError:
        return None


def _urgency_color(days: int | None) -> str:
    """Color code based on days until deadline."""
    if days is None:
        return ""
    if days < 0:
        return ""
    if days <= 7:
        return _RED
    if days <= 30:
        return _YELLOW
    return _GREEN


def print_table(conferences: list[dict], now: datetime | None = None):
    """Print conferences as colored terminal table."""
    if now is None:
        now = datetime.now(timezone.utc)

    rows = []
    for conf in conferences:
        # Find next upcoming deadline
        next_dl = None
        next_days = None
        for d in conf.get("deadlines", []):
            if d.get("passed"):
                continue
            days = _days_until(d["date"], now)
            if days is not None and (next_days is None or days < next_days):
                next_dl = d
                next_days = days

        if next_dl is None:
            # All passed — show most recent
            if conf.get("deadlines"):
                next_dl = conf["deadlines"][-1]
                next_days = _days_until(next_dl["date"], now)

        dl_label = next_dl["label"] if next_dl else "—"
        dl_date = next_dl["date"] if next_dl else "—"
        days_str = f"{next_days}d" if next_days is not None else "—"

        rows.append({
            "name": conf.get("name", "?"),
            "year": str(conf.get("year", "")),
            "area": conf.get("area", ""),
            "tier": conf.get("tier", ""),
            "deadline": dl_label,
            "date": dl_date,
            "days": days_str,
            "_days_int": next_days,
        })

    # Sort by days (soonest first), None/past at end
    rows.sort(key=lambda r: (
        r["_days_int"] is None or r["_days_int"] < 0,
        r["_days_int"] if r["_days_int"] is not None else 9999,
    ))

    # Column widths
    headers = ["Name", "Year", "Area", "Tier", "Next Deadline", "Date", "Days"]
    keys = ["name", "year", "area", "tier", "deadline", "date", "days"]
    widths = [len(h) for h in headers]
    for row in rows:
        for i, k in enumerate(keys):
            widths[i] = max(widths[i], len(str(row[k])))

    # Print header
    header_line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(f"{_BOLD}{header_line}{_RESET}")
    print("  ".join("─" * w for w in widths))

    # Print rows
    for row in rows:
        color = _urgency_color(row["_days_int"])
        reset = _RESET if color else ""
        parts = []
        for i, k in enumerate(keys):
            val = str(row[k]).ljust(widths[i])
            if k in ("date", "days", "deadline") and color:
                parts.append(f"{color}{val}{reset}")
            else:
                parts.append(val)
        print("  ".join(parts))


def cmd_show(args):
    """Show conferences from exported output as a table."""
    data = _load_output_file(args.input)
    conferences = data.get("conferences", [])
    if not conferences:
        print("No conferences in file.")
        return
    print_table(conferences)


def main():
    parser = argparse.ArgumentParser(
        prog="deadline-crawler",
        description="Crawl conference CFP pages for deadlines",
    )
    sub = parser.add_subparsers(dest="command")

    crawl_p = sub.add_parser("crawl", help="Crawl conferences and export output")
    crawl_p.add_argument("--conf", help="Crawl single conference by name")
    crawl_p.add_argument("--config", default="conferences.yaml", help="Config file path")
    crawl_p.add_argument("--year", default=None, help="Target year(s), comma-separated (e.g. 2026,2027)")
    crawl_p.add_argument("--format", "-f", choices=["json", "yaml"], default="json", help="Output format")
    crawl_p.add_argument("--output", "-o", help="Output file path")
    crawl_p.add_argument("--workers", "-w", type=int, default=4, help="Parallel fetch threads (default: 4)")

    # T10: validate command
    validate_p = sub.add_parser("validate", help="Validate exported output against invariants")
    validate_p.add_argument("--input", "-i", default="output/deadlines.json", help="Exported file to validate")

    # T11: show command (table output)
    show_p = sub.add_parser("show", help="Show conferences as colored table")
    show_p.add_argument("--input", "-i", default="output/deadlines.json", help="Exported file to display")

    args = parser.parse_args()

    if args.command == "crawl":
        cmd_crawl(args)
    elif args.command == "validate":
        cmd_validate(args)
    elif args.command == "show":
        cmd_show(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
