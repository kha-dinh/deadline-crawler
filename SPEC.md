# SPEC — deadline-crawler

## §G Goal
Crawl conference CFP pages and export structured deadline data (JSON/YAML). Per-conference crawl strategy. CLI to crawl+export and query results.

## §C Constraints
- C1: Crawler exports directly from crawl results — conferences.yaml is source of truth
- C2: Focus areas: SEC, SYS, HW, SE/PL, GEN — CORE ranked {A*, A, B, C}
- C3: Deadlines default AoE unless `timezone` field set
- C4: Minimal deps — no heavy framework
- C5: Must work offline (query exported output) + online (crawl+export)
- C6: Each conference has own crawl strategy (CSS selector, regex, LLM extract, etc.)

## §I Interfaces
- I.conf: `conferences.yaml` — crawl config per conference: name, url, strategy, tags, optional description. `section` selector always required to narrow HTML to dates region. Optional `researchr_track: str` — track slug (supports `{YYYY}` template, e.g. `icse-{YYYY}-research-track`) for researchr.org dates pages. Optional `deadlines: [{label: str, pattern: str}]` — last-resort escape hatch ONLY; forbidden unless generic A+C extractor produces wrong/missing results (see V15); each block must have inline comment explaining why generic fails. Optional `by_year: {YYYY: {url, selectors?, cycles?, overrides?}}` — per-year config for conferences with unpredictable URLs or layouts. Year-specific fields merge over top-level defaults. **Schema (T24–T26):** (1) `description: str` top-level field replaces `overrides: {description: str}` — no other overrides exist; (2) `event_selectors: {date: css, place: css}` replaces `main_selectors` — scrapes event date/place from `url_main`; implicit defaults by `url_main` pattern: `conf.researchr.org` → `{date: "div.place", place: "div.place a"}`, `usenix.org` → `{date: ".field-name-field-date-text .field-item", place: ".field-name-field-address-text .field-item"}`; explicit block only for non-standard sites; (3) cycle hoisting — shared selector fields (`items`, `label`, `date`, `researchr_track`, etc.) live in top-level `selectors`; each cycle entry is flat `{name, discriminator}` where discriminator is `section_css`, `section`, or `researchr_cycle`; strategy merges top-level `selectors` as defaults before dispatching each cycle
- I.cli: CLI commands: `crawl [--conf NAME] [--year YEAR...] [--format json|yaml] [--output PATH]`, `list [--area X] [--tier N] [--days N]`, `show [--input FILE]`, `validate`. `--year` accepts comma-separated values (e.g. `--year 2026,2027`); defaults to current year + next year; crawls each conference for each year
- I.crawl: Crawler engine — loads strategy from I.conf, fetches page, extracts fields, exports directly
- I.out: Terminal table or JSON output
- I.web: `deadlines.yaml` — frontend-consumable output. Shape: `generated_at` + `conferences[]`. Each conference: `id` (slug), `name`, `year`, `description`, `link`, `area`, `tier`, `place`, `date` (event date ISO), `timezone` (default AoE), `deadlines[]` (`label`, `date`, `passed`), `tags[]`, `comment?`
- I.strategy: Extract strategy — `regex` (pattern match). **Scaffolding check fires first** (see V22) — if page is placeholder/404, raise `ValueError` before any extraction. Three extraction modes: (1) **researchr extractor** — structural BeautifulSoup parse of researchr.org dates pages; filters `<tr href=...>` rows by track slug, reads col0 (date) + col2 (label) via `_parse_deadline_date` + `_match_label`; two sub-modes: *explicit* (`researchr_track` set in selectors, supports `{YYYY}` template + optional `researchr_cycle` filter for multi-cycle conferences) and *auto-discover* (`_autodiscover_researchr` — collects all unique `<tr href>` slugs, scores each by canonical label count + "research" in slug tiebreak, picks best; fires automatically on any page with `<tr href>` rows, no config needed); (2) **generic A+C extractor** — structure-preserving HTML→text (Phase A: table/dl/li flattening) + two-pass proximity search (Phase C: find dates then match nearby labels); primary extractor for all standard CFP pages; (3) **site-specific regex** — per-conference `deadlines:` patterns in I.conf, last-resort escape hatch only (see V15). Extraction chain: explicit researchr_track (if set) → researchr auto-discover → generic A+C extractor → site-specific patterns (last resort, if defined) → empty. Label map inverts V10: maps raw CFP phrases → canonical labels (e.g. "abstract registration" → `abstract`). Section selector remains only required site-specific config. Other strategies (css, llm, static) deferred

## §V Invariants
- V1: Every data.yaml entry MUST have: name, year, link, deadline (≥1), tags (≥1 area + tier)
- V2: deadline[] items are dicts `{label: str, date: "YYYY-MM-DD HH:MM"}` — label is canonical (see V10)
- V3: tags[] first element = area code {SEC,SYS,HW,SE,PL,GEN}, second = CORE rank {A*,A,B,C}
- V4: No duplicate (name, year) pairs in data.yaml
- V5: (removed — no data.yaml intermediary)
- V6: Past deadlines retained in output for historical reference
- V7: Every conference in conferences.yaml MUST have: name, strategy, tags. `url` required unless `by_year` provides URLs for all target years
- V8: Strategy field must be one of: regex, css (llm, static deferred)
- V9: Crawl result validated against V1-V3 before proposing to user
- V10: deadline[].label MUST be one of: {abstract, submission, early_reject, rebuttal_start, rebuttal_end, notification, shepherd, camera_ready}. Mapping from raw CFP text → canonical label lives in strategy layer
- V11: Generic extractor label map MUST cover all V10 canonical labels. Each canonical label has ≥1 phrase variant. Map is single source of truth for text→label mapping
- V12: Task completion requires: (1) unit tests pass (`uv run pytest tests/`), AND (2) smoke test pass (`uv run main.py crawl`) — all conferences must export with 0 skipped. Smoke test catches selector drift that unit tests with mocked HTML cannot
- V13: When `by_year` present for target year, resolver MUST use year-specific config merged over top-level defaults. Year-specific fields take precedence. If year absent from `by_year` AND top-level `url` has no `{YYYY}` placeholder → skip conference for that year with warning
- V14: Deadline dates SHOULD be chronologically ordered per canonical sequence: abstract ≤ submission ≤ early_reject ≤ rebuttal_start ≤ rebuttal_end ≤ notification ≤ shepherd ≤ camera_ready. Violation emits warning (not error) — some conferences have unusual timelines. Only labels present in entry are checked. Known false positive: POPL assigns shepherds before final notification (early shepherd contact in their review process) — warning fires but data is correct; do not attempt to fix
- V15: Generic A+C extractor is primary for all CFP pages. Site-specific `deadlines:` patterns MUST NOT be added unless generic produces wrong/missing results after reasonable tuning (LABEL_MAP extension, section selector adjustment). New `deadlines:` blocks require inline comment in conferences.yaml explaining why generic fails. Existing blocks MUST be removed when generic achieves correct extraction
- V16: Entry with no `abstract` or `submission` label → warn (likely incomplete crawl; entry still valid)
- V17: Duplicate label within single entry → error, reject entry (extractor bug)
- V19: `link` empty or not valid HTTP/HTTPS URL → error, reject entry
- V20: Entry with exactly 1 deadline → warn (likely partial crawl)
- V21: If entry `date` field non-empty and contains a 4-digit year, that year MUST match entry `year`. Violation → warn (not error) — some conferences span year-end (e.g. Dec/Jan event)
- V22: Strategy MUST run `_is_scaffolding(html)` immediately after fetch, before extraction chain. Scaffolding = placeholder/404 page with no real CFP content. Detection: (1) known phrases ("coming soon", "under construction", "page not found", "404 not found", etc.); (2) stripped text starts with `404`; (3) word count &lt; 75 AND no date patterns present. Scaffolding → raise `ValueError` (caught by `crawl_all` as warning). Silent empty deadlines MUST NOT be returned for scaffold pages. Both `regex` and `css` strategies enforce this
- V23: Output `deadlines[]` array MUST be sorted by canonical `LABEL_ORDER` (abstract, submission, early_reject, rebuttal_start, rebuttal_end, notification, shepherd, camera_ready). Sort applied in `transform_entry` (generate.py) after extraction. Extractor insertion order is irrelevant — output order always canonical

## §T Tasks
| id | status | task | cites |
|----|--------|------|-------|
| T1 | x | design conferences.yaml schema + seed w/ existing SEC conferences | I.conf,V7,V8 |
| T2 | x | strategy engine: load conf, dispatch to strategy handler | I.strategy,I.conf |
| T3 | x | strategy: `css` — CSS selector-based extraction | I.strategy |
| T4 | x | strategy: `regex` — fetch page, extract via regex patterns | I.strategy |
| T5 | — | (deferred) strategy: `llm` | I.strategy |
| T6 | — | (deferred) strategy: `static` | I.strategy |
| T7 | x | (removed — no diff engine needed) | — |
| T8 | x | CLI: `crawl` command — run strategies, export output | I.cli,I.crawl |
| T9 | — | (deferred) CLI: `list` command — filter by area/tier/days-until, table output | I.cli,I.out |
| T10 | x | CLI: `validate` command — check output against invariants | V1,V2,V3,V4 |
| T11 | x | output: terminal table w/ color for urgency (≤7d red, ≤30d yellow) | I.out |
| T12 | x | CI: validate on push + weekly crawl producing JSON/YAML artifacts | V1,V2,V3,V4 |
| T13 | x | output: generate deadlines.json from data.yaml for frontend | I.web,I.yaml,V1,V2,V3 |
| T14 | x | labeled deadlines: update CrawlResult.deadlines to list[dict{label,date}], update strategies + conf selectors | V2,I.conf,I.web |
| T15 | x | CLI: `--year` flag — comma-separated, crawl each conf for each year | I.cli,I.crawl |
| T16 | x | generic text extractor: strip HTML, label map (V10 inverted), generic date pattern, fallback chain in regex strategy | I.strategy,V10,V11 |
| T17 | x | generic extractor v2: structure-preserving HTML strip (Phase A) + proximity-based label matching (Phase C). Compare generic vs site-specific output per conference; remove `deadlines:` blocks where generic matches, keep as override where it doesn't | I.strategy,V10,V11,§D |
| T18 | x | `by_year` support: merge per-year config in config loader + resolve_url, remove `url_fixed`, update ASIACCS entry | I.conf,V7,V13 |
| T19 | x | date-order warning: check deadline dates follow canonical label sequence, warn on violation | V14 |
| T20 | x | researchr extractor: `_extract_deadlines_researchr` (explicit slug) + `_autodiscover_researchr` (auto-score all `<tr href>` slugs); auto-discover fires on any researchr page with no config; ICSE keeps explicit `researchr_track`+`researchr_cycle` for cycle filtering; FSE, ASE, ISSTA, ICST, MSR, ICSME, SANER `deadlines:` blocks removed | I.conf,I.strategy |
| T21 | x | implement V16,V17,V19,V20 validators in `validate` command + call on crawl output | V16,V17,V19,V20 |
| T22 | x | unit tests for V16,V17,V19,V20 validators | V16,V17,V19,V20 |
| T23 | x | V21 validator: warn when `date` field year ≠ entry year | V21 |
| T24 | x | `description` top-level field; remove `overrides:` wrapper in yaml + code | I.conf |
| T25 | x | `event_selectors` replaces `main_selectors`; implicit defaults for researchr.org + usenix.org patterns | I.conf |
| T26 | x | cycle hoisting — shared selector fields at top-level `selectors`, cycle entries flat `{name, discriminator}`; strategy merges top-level as defaults | I.conf,I.strategy |

## §D Date Parsing Pipeline

Raw CFP text → V2 format (`YYYY-MM-DD HH:MM`). Lives in `crawler/strategies/regex.py`.

### Extraction flow

1. **Section narrow** — `section` regex isolates dates region from full HTML
2. **Structure-preserving HTML→text (Phase A)** — convert HTML to text while keeping label+date paired:
   - `<tr>`: join `<td>`/`<th>` cells with ` | `, emit as single line
   - `<dl>`: merge `<dt>` + `<dd>` onto one line
   - `<li>`: flatten all inline children (incl `<strong>`, `<br>`) onto one line
   - Separators (`—`, `–`, `:`) preserved
3. **Two-pass proximity extraction (Phase C)**:
   - Pass 1: scan all lines for date-like strings (`_GENERIC_DATE_RE`)
   - Pass 2: for each date, search context (same line + ±2 lines) for label phrase via LABEL_MAP
   - Nearest label wins; same label not assigned twice
4. **Extraction chain**: explicit researchr_track → researchr auto-discover → generic A+C extractor → site-specific patterns (last resort, if defined) → empty
5. **Date parse** — captured date string → normalized `YYYY-MM-DD HH:MM`

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

### Generic extractor coverage

Phase A (structure-preserving strip) + Phase C (proximity search) handle all known CFP layouts:

| Layout | Example sites | Solved by |
|--------|--------------|-----------|
| `<td>label</td><td>date</td>` | SOSP, ATC | A — table cell join |
| `<strong>label</strong><br>date` | CCS | A — inline flatten + C — proximity |
| `date: label` (reversed) | NDSS | C — bidirectional scan |
| `label — date` | ASPLOS | A — separator preserve |
| `label: <strong>date</strong>` | USENIX, OSDI, NSDI, EuroSys | A — inline flatten |
| `<li>label: date</li>` | S&P | A — inline flatten |
| `<tr href="/track-slug"><td>date</td><td>track</td><td>label</td></tr>` (multi-track table) | researchr.org (ICSE, FSE, ASE, ISSTA, ICST, MSR, ICSME, SANER) | researchr auto-discover — scores all `<tr href>` slugs by canonical label count, picks best. Generic A+C fails: multiple tracks share label keywords, first match may be wrong track |

Most conferences only need `section` selector. Site-specific `deadlines:` patterns kept as override escape hatch, rarely needed. researchr.org pages handled automatically via `<tr href>` detection; explicit `researchr_track` + `researchr_cycle` only needed for multi-cycle conferences (ICSE).

## §B Bugs
| id | date | cause | fix |
|----|------|-------|-----|
| B1 | 2026-05-14 | POPL: shepherd date < notification date triggers V14 warning — POPL assigns shepherds before final notification (non-standard review process); data correct | no code fix; V14 annotated with known exception |
| B2 | 2026-05-15 | SIGCOMM: rebuttal_end > notification triggers V14 warning — SIGCOMM has "early notification" (accept/reject/revision) before rebuttal period, then final "review results notification" after; only the earlier one gets the `notification` label (first-match-wins); data correct | no code fix; process quirk |
| B3 | 2026-05-15 | CCS 2026: rebuttal_start listed after rebuttal_end in output — `transform_entry` preserved extraction order; extractor found `rebuttal_end` first (date range "Mar 17–20" → end date matched `rebuttal_end` label on next line before start date matched `rebuttal_start`) | sort `out_deadlines` by `LABEL_ORDER` in `transform_entry`; added V23 |
