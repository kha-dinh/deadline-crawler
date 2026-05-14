"""LLM-assisted extraction strategy (T5)."""

from crawler.strategy import BaseStrategy
from crawler.models import CrawlResult


class LlmStrategy(BaseStrategy):
    name = "llm"

    def extract(self, conf: dict, year: int) -> list[CrawlResult]:
        raise NotImplementedError("LLM strategy not yet implemented (T5)")
