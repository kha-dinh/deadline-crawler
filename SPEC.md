# SPEC — deadline-crawler

## §G Goal
Crawl conference CFP pages to build+maintain `data.yaml` of system security conference deadlines. Per-conference crawl strategy. Human reviews before write. CLI to query results.

## §C Constraints
- C1: Crawler builds `data.yaml` — crawl config is source of truth, YAML is output
- C2: Focus areas: SEC, SYS, HW, SE/PL, GEN — tiered TIER1/TIER2
- C3: Deadlines default AoE unless `timezone` field set
- C4: Minimal deps — no heavy framework
- C5: Must work offline (query local YAML) + online (crawl updates)
- C6: Each conference has own crawl strategy (CSS selector, regex, LLM extract, etc.)

## §I Interfaces
- I.conf: `conferences.yaml` — crawl config per conference: name, url, strategy, selectors/patterns, tags, metadata overrides
- I.yaml: `data.yaml` — crawled output: name, year, date, description, link, deadline[], place, tags[], notification[], timezone?, comment?
- I.cli: CLI commands: `crawl [--conf NAME]`, `list [--area X] [--tier N] [--days N]`, `show NAME`, `validate`
- I.crawl: Crawler engine — loads strategy from I.conf, fetches page, extracts fields, diffs vs I.yaml
- I.out: Terminal table or JSON output
- I.strategy: Pluggable extract strategies — `css` (selector-based), `regex` (pattern match), `llm` (LLM-assisted extract), `static` (manual override)

## §V Invariants
- V1: Every data.yaml entry MUST have: name, year, link, deadline (≥1), tags (≥1 area + tier)
- V2: deadline[] items format `"YYYY-MM-DD HH:MM"` string
- V3: tags[] first element = area code {SEC,SYS,HW,SE,PL,GEN}, second = {TIER1,TIER2}
- V4: No duplicate (name, year) pairs in data.yaml
- V5: Crawler never auto-writes data.yaml — proposes diff, human confirms
- V6: Past deadlines retained for historical reference, not deleted
- V7: Every conference in conferences.yaml MUST have: name, url, strategy, tags
- V8: Strategy field must be one of: css, regex, llm, static
- V9: Crawl result validated against V1-V3 before proposing to user

## §T Tasks
| id | status | task | cites |
|----|--------|------|-------|
| T1 | x | design conferences.yaml schema + seed w/ existing SEC conferences | I.conf,V7,V8 |
| T2 | x | strategy engine: load conf, dispatch to strategy handler | I.strategy,I.conf |
| T3 | . | strategy: `css` — fetch page, extract via CSS selectors | I.strategy |
| T4 | x | strategy: `regex` — fetch page, extract via regex patterns | I.strategy |
| T5 | . | strategy: `llm` — fetch page, send to LLM for structured extract | I.strategy |
| T6 | . | strategy: `static` — return manually specified values from conf | I.strategy |
| T7 | . | diff engine: compare crawled vs existing data.yaml, show changes | I.crawl,V5 |
| T8 | . | CLI: `crawl` command — run strategies, show diff, prompt confirm | I.cli,V5,I.crawl |
| T9 | . | CLI: `list` command — filter by area/tier/days-until, table output | I.cli,I.yaml,I.out |
| T10 | . | CLI: `validate` command — check data.yaml against invariants | V1,V2,V3,V4,I.yaml |
| T11 | . | output: terminal table w/ color for urgency (≤7d red, ≤30d yellow) | I.out |
| T12 | . | CI: validate data.yaml on every commit | V1,V2,V3,V4 |

## §B Bugs
| id | date | cause | fix |
|----|------|-------|-----|
