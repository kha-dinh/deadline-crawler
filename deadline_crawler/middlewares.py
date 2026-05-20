"""Scrapy downloader middlewares for deadline_crawler."""

from pathlib import Path

from scrapy.exceptions import IgnoreRequest
from scrapy.http import HtmlResponse


class FixtureDownloaderMiddleware:
    """Serve responses from local HTML fixture files instead of the network.

    Activated when FIXTURES_DIR setting is non-None. The spider must set
    `fixture_map` (dict[url → Path]) on itself for URL→file mapping.
    URLs without a fixture file are silently dropped (IgnoreRequest).
    """

    @classmethod
    def from_crawler(cls, crawler):
        mw = cls()
        mw.crawler = crawler
        mw.fixtures_dir = crawler.settings.get("FIXTURES_DIR")
        return mw

    def process_request(self, request):
        if not self.fixtures_dir:
            return None  # disabled — let Scrapy fetch normally

        fixture_map = getattr(self.crawler.spider, "fixture_map", {})
        path = fixture_map.get(request.url)
        if path and Path(path).exists():
            body = Path(path).read_bytes()
            return HtmlResponse(
                url=request.url,
                body=body,
                encoding="utf-8",
                request=request,
            )
        # No fixture — skip request entirely (no network in fixture mode)
        raise IgnoreRequest(f"No fixture for {request.url}")
