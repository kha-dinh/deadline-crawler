"""Scrapy extensions — progress bar and stats summary."""

import sys
import time

from scrapy import signals
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, MofNCompleteColumn, TimeElapsedColumn

_stderr = Console(stderr=True)


class ProgressExtension:
    """Rich progress bar that tracks conference-year processing."""

    def __init__(self):
        self.progress = None
        self.task = None
        self._total_set = False

    @classmethod
    def from_crawler(cls, crawler):
        ext = cls()
        crawler.signals.connect(ext.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(ext.spider_closed, signal=signals.spider_closed)
        crawler.signals.connect(ext.response_received, signal=signals.response_received)
        # Store on crawler so spider can call advance() for errback cases
        crawler.progress_ext = ext
        return ext

    def advance(self, spider=None):
        """Advance progress by 1. Called from spider errback."""
        if self.progress and self.task is not None:
            if not self._total_set and spider:
                total = getattr(spider, "total_requests", 0)
                if total:
                    self.progress.update(self.task, total=total)
                    self._total_set = True
            self.progress.advance(self.task)

    def spider_opened(self, spider):
        total = getattr(spider, "total_requests", 0)
        self.progress = Progress(
            TextColumn("[bold blue]Crawling"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=Console(stderr=True),
        )
        self.progress.start()
        self.task = self.progress.add_task("crawl", total=total or None)

    def response_received(self, response, request, spider):
        # Only count primary CFP responses, not url_main follow-ups
        cb = request.callback
        if cb and getattr(cb, "__name__", "") == "parse_cfp":
            self.advance(spider)

    def spider_closed(self, spider):
        if self.progress:
            self.progress.stop()


class StatsExtension:
    """Log a one-line crawl summary on spider close."""

    def __init__(self):
        self._start_time = None

    @classmethod
    def from_crawler(cls, crawler):
        ext = cls()
        crawler.signals.connect(ext.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(ext.spider_closed, signal=signals.spider_closed)
        return ext

    def spider_opened(self, spider):
        self._start_time = time.monotonic()

    def spider_closed(self, spider):
        stats = spider.crawler.stats.get_stats()
        duration = time.monotonic() - self._start_time if self._start_time else 0
        scraped = stats.get("item_scraped_count", 0)
        dropped = stats.get("item_dropped_count", 0)
        retries = stats.get("retry/count", 0)
        req_count = stats.get("downloader/request_count", 0)
        resp_200 = stats.get("downloader/response_status_count/200", 0)
        resp_non200 = req_count - resp_200 if req_count > resp_200 else 0

        parts = [
            f"{scraped} scraped",
            f"{dropped} dropped",
        ]
        if retries:
            parts.append(f"{retries} retries")
        parts.append(f"{resp_200} OK")
        if resp_non200:
            parts.append(f"{resp_non200} non-200")
        parts.append(f"{duration:.1f}s")

        _stderr.print(f"[dim]Stats: {', '.join(parts)}[/]")
