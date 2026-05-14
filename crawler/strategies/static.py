"""Static/manual override strategy (T6)."""

from crawler.strategy import BaseStrategy
from crawler.models import CrawlResult


class StaticStrategy(BaseStrategy):
    name = "static"

    def extract(self, conf: dict, year: int) -> list[CrawlResult]:
        raise NotImplementedError("Static strategy not yet implemented (T6)")
