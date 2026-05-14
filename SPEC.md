# SPEC — deadline-crawler

## §G Goal
Crawl conference CFP pages and export structured deadline data (JSON/YAML). Per-conference crawl strategy. CLI to crawl+export and query results.

## §C Constraints
- C1: Crawler exports directly from crawl results — conferences.yaml is source of truth
- C2: Focus areas: SEC, SYS, HW, SE/PL, GEN — tiered TIER1/TIER2
- C3: Deadlines default AoE unless `timezone` field set
- C4: Minimal deps — no heavy framework
- C5: Must work offline (query exported output) + online (crawl+export)
- C6: Each conference has own crawl strategy (CSS selector, regex, LLM extract, etc.)

## §I Interfaces
- I.conf: `conferences.yaml` — crawl config per conference: name, url, strategy, selectors/patterns, tags, metadata overrides. Selectors support optional `deadlines: [{label: str, pattern: str}]` for site-specific override; omit to use generic text extractor. `section` selector always required to narrow HTML to dates region
- I.cli: CLI commands: `crawl [--conf NAME] [--year YEAR...] [--format json|yaml] [--output PATH]`, `list [--area X] [--tier N] [--days N]`, `show NAME`, `validate`. `--year` accepts comma-separated values (e.g. `--year 2026,2027`); crawls each conference for each year
- I.crawl: Crawler engine — loads strategy from I.conf, fetches page, extracts fields, exports directly
- I.out: Terminal table or JSON output
- I.web: `deadlines.yaml` — frontend-consumable output. Shape: `generated_at` + `conferences[]`. Each conference: `id` (slug), `name`, `year`, `description`, `link`, `area`, `tier`, `place`, `date` (event date ISO), `timezone` (default AoE), `deadlines[]` (`label`, `date`, `passed`), `tags[]`, `comment?`
- I.strategy: Extract strategy — `regex` (pattern match). Two extraction modes: (1) **generic text extractor** — strip HTML tags, match canonical label phrases against generic date pattern, no per-site patterns needed; (2) **site-specific regex** — per-conference patterns in I.conf, used as override. Fallback chain: site-specific patterns (if defined) → generic text extractor → empty. Label map inverts V10: maps raw CFP phrases → canonical labels (e.g. "abstract registration" → `abstract`). Section selector remains only required site-specific config. Other strategies (css, llm, static) deferred

## §V Invariants
- V1: Every data.yaml entry MUST have: name, year, link, deadline (≥1), tags (≥1 area + tier)
- V2: deadline[] items are dicts `{label: str, date: "YYYY-MM-DD HH:MM"}` — label is canonical (see V10)
- V3: tags[] first element = area code {SEC,SYS,HW,SE,PL,GEN}, second = {TIER1,TIER2}
- V4: No duplicate (name, year) pairs in data.yaml
- V5: (removed — no data.yaml intermediary)
- V6: Past deadlines retained in output for historical reference
- V7: Every conference in conferences.yaml MUST have: name, url, strategy, tags
- V8: Strategy field must be: regex (css, llm, static deferred)
- V9: Crawl result validated against V1-V3 before proposing to user
- V10: deadline[].label MUST be one of: {abstract, submission, early_reject, rebuttal_start, rebuttal_end, notification, shepherd, camera_ready}. Mapping from raw CFP text → canonical label lives in strategy layer
- V11: Generic extractor label map MUST cover all V10 canonical labels. Each canonical label has ≥1 phrase variant. Map is single source of truth for text→label mapping
- V12: Task completion requires: (1) unit tests pass (`uv run pytest tests/`), AND (2) smoke test pass (`uv run main.py crawl`) — all conferences must export with 0 skipped. Smoke test catches selector drift that unit tests with mocked HTML cannot

## §T Tasks
| id | status | task | cites |
|----|--------|------|-------|
| T1 | x | design conferences.yaml schema + seed w/ existing SEC conferences | I.conf,V7,V8 |
| T2 | x | strategy engine: load conf, dispatch to strategy handler | I.strategy,I.conf |
| T3 | — | (deferred) strategy: `css` | I.strategy |
| T4 | x | strategy: `regex` — fetch page, extract via regex patterns | I.strategy |
| T5 | — | (deferred) strategy: `llm` | I.strategy |
| T6 | — | (deferred) strategy: `static` | I.strategy |
| T7 | x | (removed — no diff engine needed) | — |
| T8 | x | CLI: `crawl` command — run strategies, export output | I.cli,I.crawl |
| T9 | — | (deferred) CLI: `list` command — filter by area/tier/days-until, table output | I.cli,I.out |
| T10 | x | CLI: `validate` command — check output against invariants | V1,V2,V3,V4 |
| T11 | x | output: terminal table w/ color for urgency (≤7d red, ≤30d yellow) | I.out |
| T12 | x | CI: validate data.yaml on every commit | V1,V2,V3,V4 |
| T13 | x | output: generate deadlines.json from data.yaml for frontend | I.web,I.yaml,V1,V2,V3 |
| T14 | x | labeled deadlines: update CrawlResult.deadlines to list[dict{label,date}], update strategies + conf selectors | V2,I.conf,I.web |
| T15 | x | CLI: `--year` flag — comma-separated, crawl each conf for each year | I.cli,I.crawl |
| T16 | x | generic text extractor: strip HTML, label map (V10 inverted), generic date pattern, fallback chain in regex strategy | I.strategy,V10,V11 |

## §D Date Parsing Pipeline

Raw CFP text → V2 format (`YYYY-MM-DD HH:MM`). Lives in `crawler/strategies/regex.py:_parse_deadline_date()`.

### Extraction flow

1. **Section narrow** — `section` regex isolates dates region from full HTML
2. **Deadline extract** — fallback chain: site-specific patterns → generic text extractor → empty
3. **Date parse** — captured date string → normalized `YYYY-MM-DD HH:MM`

### Normalization steps (in order)

1. Replace `&nbsp;` / `&#8212;` with plain equivalents
2. Collapse multiple spaces
3. Strip day-of-week prefix: `Tuesday, ` / `Wed, ` / etc.
4. Normalize `Sept` → `Sep`
5. Strip ordinal suffixes: `3rd` → `3`, `1st` → `1`
6. Strip trailing qualifiers: `mandatory`, `optional`
7. Strip parenthetical suffixes: `(AoE)`, `(previously ...)`, `(11:59pm Eastern)`
8. Strip semicolon-delimited time: `; 23:59 PT`
9. Strip timezone suffixes: `AoE`, `UTC`, `US PDT`, `Eastern`, etc.

### Supported input formats

| Format | Example | Source |
|--------|---------|--------|
| Full month + time + tz | `Tuesday, August 26, 2025, 11:59 pm AoE` | USENIX |
| Full month, no time | `June 5, 2025` | S&P |
| Short month | `Jan 7, 2026` | CCS |
| Day-first | `23 April 2025` | NDSS |
| Semicolon time | `April 10, 2025; 23:59 PT` | SOSP |
| Ordinal day | `July 3rd, 2026` | SOSP 2026 |
| Parenthetical tz | `May 8, 2025 (AoE)` | EuroSys |
| Entity spaces | `Aug 13,&nbsp; 2025` | ASPLOS |
| Trailing qualifier | `May 29, 2025 mandatory` | S&P |

### Time defaults

- If explicit time parsed (e.g. `11:59 pm`) → use it
- If date-only → default to `23:59` (end-of-day AoE convention, per C3)

### Generic extractor label map

Maps raw CFP phrases → V10 canonical labels. Defined in `LABEL_MAP` dict. Covers all 8 canonical labels (V11). Match is case-insensitive substring. First match wins.

| Canonical label | Example phrases |
|----------------|-----------------|
| `abstract` | "abstract registration", "abstracts due", "register abstracts" |
| `submission` | "submission deadline", "paper submissions due" |
| `early_reject` | "early reject", "early rejection", "desk reject" |
| `rebuttal_start` | "rebuttal start", "reviews available" |
| `rebuttal_end` | "rebuttal due", "author response due" |
| `notification` | "author notification", "notification to authors" |
| `shepherd` | "shepherd", "conditional accept" |
| `camera_ready` | "camera ready", "camera-ready", "final paper" |

### Generic extractor limitations

Requires label + date on same line after HTML stripping. Fails on table-format sites where `<td>label</td><td>date</td>` become separate lines. Affected: SOSP, ATC, CCS. These need site-specific patterns.

## §B Bugs
| id | date | cause | fix |
|----|------|-------|-----|
