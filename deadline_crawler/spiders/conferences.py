"""Conference deadline spider — reads conferences.yaml, dispatches to extractors."""

import datetime
import re
from urllib.parse import urljoin, urlparse

import scrapy

from crawler.config import load_conferences, resolve_conf_for_year, resolve_url
from crawler.models import CrawlResult
from crawler.extractors.regex import (
    _build_cycle_selectors,
    _check_date_year_sanity,
    _is_scaffolding,
    extract_deadlines_regex,
    extract_main_fields,
    extract_main_fields_xpath,
)
from crawler.extractors.css import _extract_deadlines_css
from crawler.extractors.xpath import _extract_deadlines_xpath
from deadline_crawler.items import ConferenceItem

# CFP link discovery patterns — scored by relevance
_CFP_HREF_PATTERNS = [
    (r'\bcfp\b', 10),
    (r'call[-_]?for[-_]?papers?', 10),
    (r'call[-_]papers', 8),
    (r'important[-_]?dates?', 7),
    (r'call[-_]?for[-_]?contributions?', 6),
    (r'call[-_]?for[-_]?submissions?', 6),
    (r'\bsubmissions?\b', 4),
    (r'\bdeadlines?\b', 5),
    (r'\bpapers?\b', 2),
]

_CFP_TEXT_PATTERNS = [
    (r'call\s+for\s+papers?', 10),
    (r'\bcfp\b', 10),
    (r'important\s+dates?', 7),
    (r'call\s+for\s+contributions?', 6),
    (r'call\s+for\s+submissions?', 6),
    (r'submission\s+deadline', 5),
]

_MAX_DISCOVER_DEPTH = 2


class ConferencesSpider(scrapy.Spider):
    name = "conferences"

    def __init__(self, config=None, years=None, conf=None, **kwargs):
        super().__init__(**kwargs)
        self._config_arg = config
        if years is None:
            now = datetime.datetime.now()
            self.years = [now.year, now.year + 1]
        elif isinstance(years, str):
            self.years = [int(y.strip()) for y in years.split(",")]
        else:
            self.years = list(years)
        self.conf_filter = conf
        self.fixture_map = {}
        self.errors = []  # [(label, message), ...]

    def _build_fixture_map(self, fixtures_dir):
        """Map conference URLs → local fixture file paths."""
        import re
        from pathlib import Path

        fixtures_path = Path(fixtures_dir)
        if not fixtures_path.exists():
            self.logger.warning(f"Fixtures dir not found: {fixtures_dir}")
            return

        conferences = load_conferences(self.config_path)
        for conf in conferences:
            if self.conf_filter and conf["name"].lower() != self.conf_filter.lower():
                continue
            for year in self.years:
                resolved = resolve_conf_for_year(conf, year)
                if resolved is None:
                    continue
                slug = re.sub(r"[^a-z0-9]+", "-", conf["name"].lower()).strip("-")
                cfp_url = resolve_url(resolved, year)
                if cfp_url:
                    p = fixtures_path / f"{slug}_{year}.html"
                    if p.exists():
                        self.fixture_map[cfp_url] = p
                url_main_tmpl = resolved.get("url_main")
                if url_main_tmpl:
                    main_url = resolve_url({"url": url_main_tmpl}, year)
                    if main_url and main_url != cfp_url:
                        p = fixtures_path / f"{slug}_{year}_main.html"
                        if p.exists():
                            self.fixture_map[main_url] = p

    async def start(self):
        # Suppress noisy retry "gave up" logs — we capture errors in errback
        import logging
        logging.getLogger("scrapy.downloadermiddlewares.retry").setLevel(logging.CRITICAL)

        self.config_path = self._config_arg or self.settings.get("CONFERENCE_CONFIG", "conferences.yaml")
        fixtures_dir = self.settings.get("FIXTURES_DIR")
        if fixtures_dir:
            self._build_fixture_map(fixtures_dir)

        conferences = load_conferences(self.config_path)
        # Pre-count total requests for progress bar
        requests = []
        for conf in conferences:
            if self.conf_filter and conf["name"].lower() != self.conf_filter.lower():
                continue
            for year in self.years:
                resolved = resolve_conf_for_year(conf, year)
                if resolved is None:
                    continue
                url = resolve_url(resolved, year)
                if not url:
                    continue
                requests.append((resolved, year, url))
        self.total_requests = len(requests)

        for resolved, year, url in requests:
            yield scrapy.Request(
                url,
                callback=self.parse_cfp,
                cb_kwargs={"conf": resolved, "year": year},
                dont_filter=True,
                errback=self.handle_error,
            )

    def handle_error(self, failure):
        from scrapy.exceptions import IgnoreRequest
        progress_ext = getattr(self.crawler, "progress_ext", None)
        if failure.check(IgnoreRequest):
            # Advance progress for fixture-mode skips too
            if progress_ext:
                progress_ext.advance(self)
            return
        url = failure.request.url
        reason = str(failure.value).split("\n")[0]
        cb_kwargs = failure.request.cb_kwargs
        conf = cb_kwargs.get("conf", {})
        year = cb_kwargs.get("year", "")
        label = f"{conf.get('name', url)} {year}".strip()
        self.errors.append((label, f"fetch failed: {reason}"))
        if progress_ext:
            progress_ext.advance(self)

    def _find_cfp_link(self, response):
        """Scan page for CFP-like links, return best URL or None."""
        base_domain = urlparse(response.url).netloc
        candidates = []

        for link in response.css("a[href]"):
            href = link.attrib.get("href", "").strip()
            if not href or href.startswith(("#", "mailto:", "javascript:")):
                continue

            abs_url = urljoin(response.url, href)
            # Skip off-domain links
            if urlparse(abs_url).netloc != base_domain:
                continue
            # Skip self-links
            if abs_url.rstrip("/") == response.url.rstrip("/"):
                continue

            text = link.css("::text").get() or ""
            text = text.strip()
            href_lower = href.lower()
            text_lower = text.lower()

            score = 0
            for pattern, pts in _CFP_HREF_PATTERNS:
                if re.search(pattern, href_lower):
                    score += pts
            for pattern, pts in _CFP_TEXT_PATTERNS:
                if re.search(pattern, text_lower):
                    score += pts

            if score > 0:
                candidates.append((score, abs_url, text))

        if not candidates:
            return None

        candidates.sort(key=lambda x: -x[0])
        best_score, best_url, best_text = candidates[0]
        self.logger.debug(
            f"CFP discovery: best link '{best_text}' ({best_url}) score={best_score}"
        )
        return best_url

    def parse_cfp(self, response, conf, year):
        if response.status != 200:
            label = f"{conf['name']} {year}"
            self.errors.append((label, f"HTTP {response.status} from {response.url}"))
            return

        if _is_scaffolding(response.text):
            self.logger.debug(f"{conf['name']} {year}: scaffolding page at {response.url}")
            return

        # Check if url_main differs from CFP URL
        url_main = resolve_url(
            {"url": conf.get("url_main", conf.get("url"))}, year
        )
        if url_main and url_main != response.url:
            yield scrapy.Request(
                url_main,
                callback=self.parse_with_main,
                cb_kwargs={
                    "conf": conf,
                    "year": year,
                    "cfp_html": response.text,
                    "cfp_url": response.url,
                },
                dont_filter=True,
                errback=self.handle_error,
            )
        else:
            # Try extraction, fall back to CFP discovery if no deadlines found
            items = list(self._extract(conf, year, response.text, response.url, main_html=None))
            has_deadlines = any(item.get("deadlines") for item in items)
            if has_deadlines:
                yield from items
            elif conf.get("discover_cfp", True):
                cfp_url = self._find_cfp_link(response)
                if cfp_url:
                    self.logger.debug(f"{conf['name']} {year}: discovering CFP at {cfp_url}")
                    yield scrapy.Request(
                        cfp_url,
                        callback=self.parse_discovered_cfp,
                        cb_kwargs={
                            "conf": conf,
                            "year": year,
                            "base_html": response.text,
                            "base_url": response.url,
                            "depth": 1,
                        },
                        dont_filter=True,
                        errback=self.handle_error,
                    )

    def parse_discovered_cfp(self, response, conf, year, base_html, base_url, depth=1):
        """Parse a discovered CFP page. Chains discovery up to _MAX_DISCOVER_DEPTH."""
        if response.status != 200:
            label = f"{conf['name']} {year}"
            self.errors.append((label, f"HTTP {response.status} from discovered CFP {response.url}"))
            return

        if _is_scaffolding(response.text):
            return

        # Try extraction from discovered page
        items = list(self._extract(conf, year, response.text, response.url, main_html=base_html))
        has_deadlines = any(item.get("deadlines") for item in items)
        if has_deadlines:
            yield from items
        elif depth < _MAX_DISCOVER_DEPTH and conf.get("discover_cfp", True):
            # Chain: try discovering CFP link from this intermediate page
            cfp_url = self._find_cfp_link(response)
            if cfp_url and cfp_url.rstrip("/") != base_url.rstrip("/"):
                self.logger.debug(f"{conf['name']} {year}: chained discovery depth={depth+1} at {cfp_url}")
                yield scrapy.Request(
                    cfp_url,
                    callback=self.parse_discovered_cfp,
                    cb_kwargs={
                        "conf": conf,
                        "year": year,
                        "base_html": base_html,
                        "base_url": base_url,
                        "depth": depth + 1,
                    },
                    dont_filter=True,
                    errback=self.handle_error,
                )

    def parse_with_main(self, response, conf, year, cfp_html, cfp_url):
        if response.status != 200:
            label = f"{conf['name']} {year}"
            self.errors.append((label, f"HTTP {response.status} from main page {response.url}"))
            # Still extract from CFP page alone
            yield from self._extract(conf, year, cfp_html, cfp_url, main_html=None)
            return
        yield from self._extract(conf, year, cfp_html, cfp_url, main_html=response.text)

    def _extract(self, conf, year, cfp_html, cfp_url, main_html):
        """Dispatch to correct extractor based on strategy, yield ConferenceItems."""
        try:
            yield from self._extract_inner(conf, year, cfp_html, cfp_url, main_html)
        except Exception as e:
            label = f"{conf['name']} {year}"
            self.errors.append((label, f"extraction failed ({type(e).__name__}: {e})"))

    def _extract_inner(self, conf, year, cfp_html, cfp_url, main_html):
        strategy = conf["strategy"]

        # Extract event date/place from main page
        if strategy == "xpath":
            date, place = extract_main_fields_xpath(conf, year, cfp_url, cfp_html, main_html)
        else:
            date, place = extract_main_fields(conf, year, cfp_url, cfp_html, main_html)

        no_specific = conf.get("_no_specific", False)
        conf_prefix = conf["name"].lower()

        cycles = conf.get("cycles")
        if cycles:
            for cycle in cycles:
                selectors = _build_cycle_selectors(conf, cycle)
                deadlines = self._extract_deadlines(strategy, selectors, cfp_html, year, no_specific, conf_prefix)
                try:
                    _check_date_year_sanity(deadlines, year, conf["name"], cfp_url)
                except ValueError as e:
                    label = f"{conf['name']} {year}"
                    if cycle.get("name"):
                        label += f" ({cycle['name']})"
                    self.errors.append((label, "stale CFP (dates from wrong year)"))
                    continue
                yield self._make_item(conf, year, cfp_url, deadlines, cycle.get("name"), date, place)
        else:
            selectors = conf.get("selectors", {})
            deadlines = self._extract_deadlines(strategy, selectors, cfp_html, year, no_specific, conf_prefix)
            try:
                _check_date_year_sanity(deadlines, year, conf["name"], cfp_url)
            except ValueError as e:
                self.errors.append((f"{conf['name']} {year}", "stale CFP (dates from wrong year)"))
                return
            yield self._make_item(conf, year, cfp_url, deadlines, None, date, place)

    def _extract_deadlines(self, strategy, selectors, html, year, no_specific, conf_prefix):
        """Call the right extraction function based on strategy name."""
        if strategy == "css":
            return _extract_deadlines_css(selectors, html, year)
        elif strategy == "xpath":
            return _extract_deadlines_xpath(selectors, html, year)
        else:
            # regex (default)
            return extract_deadlines_regex(
                selectors, html, year,
                no_specific=no_specific, conf_prefix=conf_prefix,
            )

    def _make_item(self, conf, year, url, deadlines, cycle, date, place):
        """Build a ConferenceItem from extracted data."""
        item = ConferenceItem()
        item["name"] = conf["name"]
        item["year"] = year
        item["link"] = url
        item["deadlines"] = deadlines
        item["tags"] = list(conf.get("tags", []))
        if cycle:
            item["cycle"] = cycle
        if date:
            item["date"] = date
        if place:
            item["place"] = place
        if conf.get("description"):
            item["description"] = conf["description"]
        return item
