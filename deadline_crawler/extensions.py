"""Scrapy extensions — progress bar for crawl status."""

import sys

from scrapy import signals
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, MofNCompleteColumn, TimeElapsedColumn


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
