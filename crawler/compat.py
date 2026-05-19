"""Compatibility layer for tests — provides crawl_conference without Scrapy.

Uses extractors directly with a simple _fetch function for HTTP.
This module exists so that fixture-based integration tests can run
without starting a Scrapy reactor.
"""

from crawler.config import resolve_conf_for_year, resolve_url
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


# Default fetch — can be monkey-patched in tests
def _fetch(url: str) -> str:
    import requests
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.encoding = resp.apparent_encoding
    return resp.text


def crawl_conference(conf: dict, year: int, no_specific: bool = False) -> list[CrawlResult]:
    """Crawl a single conference using extractors directly (no Scrapy).

    Drop-in replacement for the old crawler.strategy.crawl_conference.
    """
    resolved = resolve_conf_for_year(conf, year)
    if resolved is None:
        return []
    if no_specific:
        resolved = {**resolved, "_no_specific": True}

    url = resolve_url(resolved, year)
    if not url:
        raise ValueError(f"{conf['name']}: no URL configured")

    html = _fetch(url)

    if _is_scaffolding(html):
        raise ValueError(f"{conf['name']}: scaffolding/placeholder page detected at {url}")

    strategy = resolved["strategy"]

    # Fetch url_main if needed
    url_main = resolve_url(
        {"url": resolved.get("url_main", resolved.get("url"))}, year
    )
    main_html = None
    if url_main and url_main != url:
        main_html = _fetch(url_main)

    # Extract event fields
    if strategy == "xpath":
        date, place = extract_main_fields_xpath(resolved, year, url, html, main_html)
    else:
        date, place = extract_main_fields(resolved, year, url, html, main_html)

    no_specific = resolved.get("_no_specific", False)
    conf_prefix = resolved["name"].lower()

    def _extract_deadlines(selectors, html, year):
        if strategy == "css":
            return _extract_deadlines_css(selectors, html, year)
        elif strategy == "xpath":
            return _extract_deadlines_xpath(selectors, html, year)
        else:
            return extract_deadlines_regex(
                selectors, html, year,
                no_specific=no_specific, conf_prefix=conf_prefix,
            )

    cycles = resolved.get("cycles")
    if cycles:
        results = []
        for cycle in cycles:
            selectors = _build_cycle_selectors(resolved, cycle)
            deadlines = _extract_deadlines(selectors, html, year)
            _check_date_year_sanity(deadlines, year, resolved["name"], url)
            results.append(CrawlResult(
                name=resolved["name"],
                year=year,
                link=url,
                deadlines=deadlines,
                cycle=cycle.get("name"),
                date=date,
                place=place,
                description=resolved.get("description"),
                tags=list(resolved.get("tags", [])),
            ))
        return results
    else:
        selectors = resolved.get("selectors", {})
        deadlines = _extract_deadlines(selectors, html, year)
        _check_date_year_sanity(deadlines, year, resolved["name"], url)
        return [CrawlResult(
            name=resolved["name"],
            year=year,
            link=url,
            deadlines=deadlines,
            date=date,
            place=place,
            description=resolved.get("description"),
            tags=list(resolved.get("tags", [])),
        )]
