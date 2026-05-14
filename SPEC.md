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
- I.conf: `conferences.yaml` — crawl config per conference: name, url, strategy, selectors/patterns, tags, metadata overrides. Selectors support `deadlines: [{label: str, pattern: str}]` for multi-deadline extraction
- I.cli: CLI commands: `crawl [--conf NAME] [--year YEAR...] [--format json|yaml] [--output PATH]`, `list [--area X] [--tier N] [--days N]`, `show NAME`, `validate`. `--year` accepts comma-separated values (e.g. `--year 2026,2027`); crawls each conference for each year
- I.crawl: Crawler engine — loads strategy from I.conf, fetches page, extracts fields, exports directly
- I.out: Terminal table or JSON output
- I.web: `deadlines.yaml` — frontend-consumable output. Shape: `generated_at` + `conferences[]`. Each conference: `id` (slug), `name`, `year`, `description`, `link`, `area`, `tier`, `place`, `date` (event date ISO), `timezone` (default AoE), `deadlines[]` (`label`, `date`, `passed`), `tags[]`, `comment?`
- I.strategy: Extract strategy — `regex` (pattern match). Other strategies (css, llm, static) deferred

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

## §B Bugs
| id | date | cause | fix |
|----|------|-------|-----|
