# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run all tests
uv run pytest tests/ -v

# Run single test file
uv run pytest tests/test_regex_strategy.py -v

# Run single test
uv run pytest tests/test_regex_strategy.py::test_parse_deadline_date_basic -v

# Crawl all conferences
uv run python main.py crawl --format json

# Crawl single conference
uv run python main.py crawl --conf "USENIX Security" --format json

# Validate output
uv run python main.py validate --input output/deadlines.json

# Show colored table
uv run python main.py show --input output/deadlines.json
```

Use `uv` for all Python operations (never pip).

## Architecture

**CLI** (`main.py`): argparse with 3 subcommands — `crawl`, `validate`, `show`.

**Strategy pattern** (`crawler/strategy.py`): `BaseStrategy` ABC with `extract(conf, year) → list[CrawlResult]`. Subclasses auto-register via `__init_subclass__` with a `name` class attribute. Dispatch via `get_strategy(name)`. Only `regex` strategy is implemented; `css`, `llm`, `static` are stubs.

**RegexStrategy** (`crawler/strategies/regex.py`): Three-phase pipeline:
- Phase A: HTML → structured text (`_strip_html`) — tables use ` | `, `<dl>` merged, `<li>` flattened
- Phase C: Label matching (`_match_label`) — inverted `LABEL_MAP` maps CFP phrases → canonical labels
- Extraction: site-specific patterns first (from `conf.selectors.deadlines`), falls back to generic A+C extractor

Multi-cycle support: conferences with `cycles[]` in config produce one `CrawlResult` per cycle.

**Config** (`crawler/config.py`): Loads `conferences.yaml`, validates V7/V8 invariants. URL templates use `{YYYY}`/`{YY}` placeholders resolved at crawl time.

**Output** (`crawler/output/generate.py`): Transforms `CrawlResult` list → JSON/YAML with validation against V1-V3, V10 invariants.

## Key Invariants (from SPEC.md §V)

- **V1**: Every entry needs: name, year, link, ≥1 deadline, tags (area + tier)
- **V2**: Deadline format: `{label: str, date: "YYYY-MM-DD HH:MM"}`
- **V3**: tags = `[area_code, core_rank]` where area ∈ {SEC,SYS,HW,SE,PL,GEN}, core_rank ∈ {A*,A,B,C}
- **V7**: conferences.yaml entries require: name, url, strategy, tags
- **V8**: strategy ∈ {regex, css, llm, static}
- **V10**: Canonical deadline labels: abstract, submission, early_reject, rebuttal_start, rebuttal_end, notification, shepherd, camera_ready

## conferences.yaml Structure

Each entry has: `name`, `url` (with `{YYYY}/{YY}` templates), `strategy`, `tags`. Optional: `url_main`, `cycles[]`, `selectors`, `overrides`, `main_selectors`, `by_year`. Cycles contain `name` + `selectors.section` (regex to isolate cycle text) + optional `selectors.deadlines[]` (site-specific patterns with `label` + `pattern`).
