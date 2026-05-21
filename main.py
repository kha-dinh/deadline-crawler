"""CLI entry point for deadline-crawler."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console

from crawler.strategy import crawl_all
from crawler.output.generate import generate_from_results, _validate_entry, _validate_entry_warnings

_stderr = Console(stderr=True)


def _parse_years(raw: str | None) -> list[int] | None:
    """Parse comma-separated year string into list of ints."""
    if raw is None:
        return None
    return [int(y.strip()) for y in raw.split(",")]


def _patch_fetch_with_fixtures(fixtures_dir: Path, config: str, name_filter: str | None, years: list[int]):
    """Monkey-patch _fetch in both strategy modules to load from local fixture files."""
    import crawler.strategies.regex as _regex_mod
    import crawler.strategies.css as _css_mod
    import crawler.strategies.xpath as _xpath_mod
    from crawler.config import load_conferences, resolve_conf_for_year, resolve_url as _resolve_url

    url_map: dict[str, Path] = {}
    for conf in load_conferences(config):
        if name_filter and conf["name"].lower() != name_filter.lower():
            continue
        for year in years:
            resolved = resolve_conf_for_year(conf, year)
            if resolved is None:
                continue
            slug = _slugify_name(conf["name"])
            cfp_url = _resolve_url(resolved, year)
            if cfp_url:
                p = fixtures_dir / f"{slug}_{year}.html"
                if p.exists():
                    url_map[cfp_url] = p
            url_main_tmpl = resolved.get("url_main")
            if url_main_tmpl:
                main_url = _resolve_url({"url": url_main_tmpl}, year)
                if main_url and main_url != cfp_url:
                    p = fixtures_dir / f"{slug}_{year}_main.html"
                    if p.exists():
                        url_map[main_url] = p

    missing = []

    def _fixture_fetch(url: str) -> str:
        if url in url_map:
            return url_map[url].read_text(encoding="utf-8")
        missing.append(url)
        raise FileNotFoundError(f"No fixture for URL: {url}\nRun: uv run python main.py fetch")

    _regex_mod._fetch = _fixture_fetch
    _css_mod._fetch = _fixture_fetch
    _xpath_mod._fetch = _fixture_fetch
    return url_map, missing


def cmd_crawl(args):
    """Crawl conferences and export output."""
    years = _parse_years(args.year)

    if args.fixtures:
        fixtures_dir = Path(args.fixtures)
        if not fixtures_dir.exists():
            _stderr.print(f"[bold red]✗[/] Fixtures dir not found: {fixtures_dir}")
            _stderr.print("Run: uv run python main.py fetch")
            sys.exit(1)
        import datetime as _dt
        effective_years = years or [_dt.datetime.now().year, _dt.datetime.now().year + 1]
        url_map, _ = _patch_fetch_with_fixtures(fixtures_dir, args.config, args.conf, effective_years)
        _stderr.print(f"[dim]Using fixtures from {fixtures_dir}/ ({len(url_map)} URL(s) mapped)[/]")

    try:
        results = crawl_all(
            config_path=args.config,
            years=years,
            name_filter=args.conf,
            workers=args.workers,
            no_specific=args.no_specific,
        )
    except Exception as e:
        _stderr.print(f"[bold red]✗[/] Crawl failed: {e}")
        sys.exit(1)

    if not results:
        print("No results.")
        return

    try:
        output = generate_from_results(
            results,
            output_path=args.output,
            fmt=args.format,
            strict=args.strict,
        )
    except ValueError as e:
        _stderr.print(f"[bold red]✗[/] {e}")
        sys.exit(1)

    n = len(output["conferences"])
    out_path = args.output or f"output/deadlines.{args.format}"
    print(f"\nExported {n} conference(s) → {out_path}")


# --- T10: validate command ---


def _load_output_file(path: str) -> dict:
    """Load exported deadlines file (JSON or YAML)."""
    p = Path(path)
    if not p.exists():
        _stderr.print(f"[bold red]✗[/] File not found: {path}")
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
        "area": conf.get("area", ""),
        "rank": conf.get("rank", "unknown"),
    }


def cmd_validate(args):
    """Validate exported output against invariants V1-V4, V10, V14, V16, V17, V19, V20."""
    from crawler.output.generate import _check_date_order, _check_v16, _check_v20
    data = _load_output_file(args.input)
    conferences = data.get("conferences", [])

    if not conferences:
        print("No conferences found in file.")
        return

    seen = set()
    total_errors = 0
    total_warnings = 0

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
            _stderr.print(f"[bold red]✗[/] {conf.get('name', '?')} ({conf.get('year', '?')}):")
            for e in errors:
                _stderr.print(f"    {e}")

        name = conf.get("name", "?")
        year = conf.get("year", "?")

        # V16: no abstract/submission — error in strict mode
        v16_issues = _check_v16(entry)
        if v16_issues:
            if args.strict:
                total_errors += len(v16_issues)
                _stderr.print(f"[bold red]✗[/] {name} ({year}):")
                for w in v16_issues:
                    _stderr.print(f"    {w}")
            else:
                total_warnings += len(v16_issues)
                for w in v16_issues:
                    _stderr.print(f"[bold yellow]⚠[/] {name} ({year}): {w}")

        # V20: < 2 deadlines — error in strict mode
        v20_issues = _check_v20(entry)
        if v20_issues:
            if args.strict:
                total_errors += len(v20_issues)
                _stderr.print(f"[bold red]✗[/] {name} ({year}):")
                for w in v20_issues:
                    _stderr.print(f"    {w}")
            else:
                total_warnings += len(v20_issues)
                for w in v20_issues:
                    _stderr.print(f"[bold yellow]⚠[/] {name} ({year}): {w}")

        # V21: always warn only
        other_warnings = [w for w in _validate_entry_warnings(entry) if w not in v16_issues and w not in v20_issues]
        if other_warnings:
            total_warnings += len(other_warnings)
            for w in other_warnings:
                _stderr.print(f"[bold yellow]⚠[/] {name} ({year}): {w}")

        # V14: date order — warn normally, error in strict mode
        order_issues = _check_date_order(entry)
        if order_issues:
            if args.strict:
                total_errors += len(order_issues)
                _stderr.print(f"[bold red]✗[/] {name} ({year}):")
                for w in order_issues:
                    _stderr.print(f"    {w}")
            else:
                total_warnings += len(order_issues)
                for w in order_issues:
                    _stderr.print(f"[bold yellow]⚠[/] {name} ({year}): {w}")

    summary_parts = [f"✓ {len(conferences)} conference(s) valid."] if total_errors == 0 else []
    if total_warnings:
        summary_parts.append(f"{total_warnings} warning(s).")

    if total_errors == 0:
        print(" ".join(summary_parts) if summary_parts else f"✓ {len(conferences)} conference(s) valid.")
    else:
        _stderr.print(f"\n[bold red]{total_errors} error(s)[/] in {len(conferences)} conference(s).")
        sys.exit(1)


# --- T11: terminal table with color ---

# ANSI color codes
_RED = "\033[31m"
_YELLOW = "\033[33m"
_GREEN = "\033[32m"
_DIM = "\033[2m"
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
        return _DIM
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
            days = _days_until(d["date"], now)
            if days is not None and days < 0:
                continue
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
        is_past = row["_days_int"] is not None and row["_days_int"] < 0
        reset = _RESET if color else ""
        parts = []
        for i, k in enumerate(keys):
            val = str(row[k]).ljust(widths[i])
            if is_past:
                # Dim entire row for past/ongoing conferences
                parts.append(f"{_DIM}{val}{_RESET}")
            elif k in ("date", "days", "deadline") and color:
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


# --- fetch command: download CFP pages as fixtures ---

def _slugify_name(name: str) -> str:
    """Simple slug: lowercase, non-alphanumeric → hyphen, strip edges."""
    import re
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def cmd_fetch(args):
    """Fetch CFP HTML pages and save as test fixtures."""
    from crawler.config import load_conferences, resolve_conf_for_year, resolve_url
    from crawler.strategies.regex import _fetch

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    years = _parse_years(args.year) or [2026]
    conferences = load_conferences(args.config)

    if args.conf:
        conferences = [c for c in conferences if c["name"].lower() == args.conf.lower()]
        if not conferences:
            _stderr.print(f"[bold red]✗[/] No conference named '{args.conf}'")
            sys.exit(1)

    saved = 0
    for conf in conferences:
        for year in years:
            resolved = resolve_conf_for_year(conf, year)
            if resolved is None:
                _stderr.print(f"[dim]skip[/] {conf['name']} {year}: no config for year")
                continue

            cfp_url = resolve_url(resolved, year)
            if not cfp_url:
                _stderr.print(f"[dim]skip[/] {conf['name']} {year}: no URL")
                continue

            slug = _slugify_name(conf["name"])
            cfp_path = outdir / f"{slug}_{year}.html"

            try:
                html = _fetch(cfp_url)
                cfp_path.write_text(html, encoding="utf-8")
                print(f"✓ {conf['name']} {year} → {cfp_path}")
                saved += 1
            except Exception as e:
                _stderr.print(f"[bold red]✗[/] {conf['name']} {year}: {e}")
                continue

            # Fetch url_main separately if it differs from cfp_url
            url_main_tmpl = resolved.get("url_main")
            if url_main_tmpl:
                main_url = resolve_url({"url": url_main_tmpl}, year)
                if main_url and main_url != cfp_url:
                    main_path = outdir / f"{slug}_{year}_main.html"
                    try:
                        main_html = _fetch(main_url)
                        main_path.write_text(main_html, encoding="utf-8")
                        print(f"  ↳ main → {main_path}")
                    except Exception as e:
                        _stderr.print(f"  [yellow]⚠[/] main page failed: {e}")

    print(f"\n{saved} fixture(s) saved to {outdir}/")


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
    crawl_p.add_argument("--workers", "-w", type=int, default=8, help="Parallel fetch threads (default: 8)")
    crawl_p.add_argument("--no-specific", action="store_true", default=False, help="Skip site-specific deadline patterns; use generic extractor only")
    crawl_p.add_argument("--fixtures", metavar="DIR", nargs="?", const="tests/fixtures", default=None, help="Load HTML from local fixtures instead of fetching live (default dir: tests/fixtures)")
    crawl_p.add_argument("--strict", action="store_true", default=False, help="Treat date order violations (V14) as errors instead of warnings")

    # T10: validate command
    validate_p = sub.add_parser("validate", help="Validate exported output against invariants")
    validate_p.add_argument("--input", "-i", default="output/deadlines.json", help="Exported file to validate")
    validate_p.add_argument("--strict", action="store_true", default=False, help="Treat date order violations (V14) as errors instead of warnings")

    # T11: show command (table output)
    show_p = sub.add_parser("show", help="Show conferences as colored table")
    show_p.add_argument("--input", "-i", default="output/deadlines.json", help="Exported file to display")

    # fetch command: download CFP pages as test fixtures
    fetch_p = sub.add_parser("fetch", help="Download CFP pages as HTML fixtures for testing")
    fetch_p.add_argument("--conf", help="Fetch single conference by name")
    fetch_p.add_argument("--config", default="conferences.yaml", help="Config file path")
    fetch_p.add_argument("--year", default="2026", help="Target year(s), comma-separated (default: 2026)")
    fetch_p.add_argument("--outdir", default="tests/fixtures", help="Output directory for fixtures (default: tests/fixtures)")

    args = parser.parse_args()

    if args.command == "crawl":
        cmd_crawl(args)
    elif args.command == "validate":
        cmd_validate(args)
    elif args.command == "show":
        cmd_show(args)
    elif args.command == "fetch":
        cmd_fetch(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
