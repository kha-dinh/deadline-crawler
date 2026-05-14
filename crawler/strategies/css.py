"""CSS selector-based extraction strategy (T3)."""

from crawler.strategy import BaseStrategy
from crawler.models import CrawlResult


class CssStrategy(BaseStrategy):
    name = "css"

    def extract(self, conf: dict, year: int) -> list[CrawlResult]:
        raise NotImplementedError("CSS strategy not yet implemented (T3)")
