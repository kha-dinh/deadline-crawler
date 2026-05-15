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

# Crawl from local fixtures (skips network, default dir: tests/fixtures)
uv run python main.py crawl --fixtures

# Download CFP pages as fixtures for offline testing
uv run python main.py fetch --year 2026,2027

# Validate output (--strict treats date-order violations as errors)
uv run python main.py validate --input output/deadlines.json --strict

# Show colored table
uv run python main.py show --input output/deadlines.json
```

Use `uv` for all Python operations (never pip).

## Architecture

**CLI** (`main.py`): argparse with 4 subcommands — `crawl`, `validate`, `show`, `fetch`.
- `crawl` flags: `--conf`, `--year` (comma-separated), `--format`, `--output`, `--workers` (default 8), `--fixtures [DIR]`, `--no-specific` (skip site-specific patterns, use generic only), `--strict` (V14 violations → errors)
- `fetch`: downloads live CFP HTML to `tests/fixtures/` as `{slug}_{year}.html` for offline use
- `validate`/`crawl` share `--strict`: promotes date-order warnings (V14) to errors

**Strategy pattern** (`crawler/strategy.py`): `BaseStrategy` ABC with `extract(conf, year) → list[CrawlResult]`. Subclasses auto-register via `__init_subclass__` with a `name` class attribute. Dispatch via `get_strategy(name)`. `regex` and `css` are implemented; `llm`, `static` are stubs.

**RegexStrategy** (`crawler/strategies/regex.py`): Extraction chain (in order):
1. **Researchr explicit** — if `selectors.researchr_track` set, parse researchr.org `<tr href>` rows filtered by track slug (supports `{YYYY}` template + optional `researchr_cycle`)
2. **Researchr auto-discover** — on any page with `<tr href>` rows, `_autodiscover_researchr` scores all unique slugs by canonical label count (tiebreak: "research" in slug), picks best; fires automatically with no config
3. **Generic A+C extractor** — Phase A: structure-preserving HTML→text (tables → ` | `, `<dl>` merged, `<li>` flattened); Phase C: two-pass proximity search (find dates, match ±2 lines for label via `LABEL_MAP`)
4. **Site-specific patterns** (last resort) — per-conference `selectors.deadlines[]` in config, only if generic fails; requires inline comment explaining why

Scaffolding check (`_is_scaffolding`) fires before extraction — raises `ValueError` for placeholder/404 pages.

Multi-cycle support: conferences with `cycles[]` produce one `CrawlResult` per cycle.

**CSSStrategy** (`crawler/strategies/css.py`): CSS selector-based extraction. Config shape: `section_css` (narrow DOM), `items` (per-item selector), `label`/`date` sub-selectors. Falls back to `LABEL_MAP` + `_GENERIC_DATE_RE` from regex module when sub-selectors omitted. Shares scaffolding check.

**Config** (`crawler/config.py`): Loads `conferences.yaml`, validates V7/V8 invariants. URL templates use `{YYYY}`/`{YY}` placeholders resolved at crawl time. `by_year` support: per-year config merges over top-level defaults; year-specific fields take precedence. After loading, injects CORE rank into `tags[1]` from `data/core2026.csv` via `crawler/ranks.py`; uses `core_acronym` field when conference name differs from CORE portal acronym; falls back to `core_rank` field when CSV rank is absent or non-standard.

**Rankings** (`crawler/ranks.py`): Loads `data/core2026.csv` (downloaded from CORE portal, ICORE2026 source) into `{acronym_lower: rank}` dict. First match wins on duplicate acronyms. `load_ranks()` returns empty dict if CSV missing (graceful degradation).

**Output** (`crawler/output/generate.py`): Transforms `CrawlResult` list → JSON/YAML with validation against V1-V3, V10 invariants.

## Key Invariants (from SPEC.md §V)

- **V1**: Every entry needs: name, year, link, ≥1 deadline, tags (area + tier)
- **V2**: Deadline format: `{label: str, date: "YYYY-MM-DD HH:MM"}`
- **V3**: tags = `[area_code, core_rank]` where area ∈ {SEC,SYS,HW,SE,PL,GEN}, core_rank ∈ {A*,A,B,C}
- **V7**: conferences.yaml entries require: name, strategy, tags. `url` required unless `by_year` covers all target years
- **V8**: strategy ∈ {regex, css} (llm, static deferred)
- **V10**: Canonical deadline labels: abstract, submission, early_reject, rebuttal_start, rebuttal_end, notification, shepherd, camera_ready
- **V14**: Deadline dates should follow canonical order; violation → warning (error with `--strict`). Known false positive: POPL shepherd < notification (correct data)
- **V15**: Generic A+C extractor is primary. Site-specific `deadlines:` blocks require inline comment and must be removed when generic achieves correct extraction
- **V22**: `_is_scaffolding` fires before extraction; scaffolding → `ValueError`, never silent empty results

## conferences.yaml Structure

Each entry has: `name`, `url` (with `{YYYY}/{YY}` templates), `strategy`, `tags`. Optional: `url_main`, `cycles[]`, `selectors`, `by_year`, `core_acronym`, `core_rank`. `by_year: {YYYY: {url, selectors?, cycles?, overrides?}}` — per-year config for conferences with unpredictable URLs; merges over top-level defaults. Cycles contain `name` + `selectors.section` (regex to isolate cycle text) + optional `selectors.researchr_track`/`researchr_cycle` for researchr.org multi-cycle pages.

`tags` contains only the area code: `[SEC]`, `[SYS]`, etc. — rank is injected at load time from `data/core2026.csv`. `core_acronym` overrides name-based CSV lookup (e.g. `ACM CCS` → `CCS`). `core_rank` provides explicit fallback when CSV rank is absent or non-standard (e.g. NSDI's "National: USA").
