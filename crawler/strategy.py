"""Strategy engine: dispatch conference config to the right handler (I.strategy)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from crawler.config import load_conferences, resolve_url
from crawler.models import CrawlResult

# Strategy registry — populated by strategy modules on import
_registry: dict[str, type[BaseStrategy]] = {}


class BaseStrategy(ABC):
    """Base class for all crawl strategies."""

    name: str  # must match V8 values: css, regex, llm, static

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if hasattr(cls, "name") and cls.name:
            _registry[cls.name] = cls

    @abstractmethod
    def extract(self, conf: dict, year: int) -> list[CrawlResult]:
        """Extract conference data using this strategy.

        Returns one CrawlResult per cycle. Conferences without cycles
        return a single-element list.

        Args:
            conf: Conference config entry from conferences.yaml
            year: Target year to crawl for
        """
        ...


def get_strategy(name: str) -> BaseStrategy:
    """Get strategy instance by name. Raises KeyError if not registered."""
    if name not in _registry:
        raise KeyError(
            f"Unknown strategy '{name}'. Registered: {list(_registry.keys())}"
        )
    return _registry[name]()


def _ensure_strategies_loaded():
    """Import strategy modules to trigger registration."""
    import crawler.strategies.css
    import crawler.strategies.regex
    import crawler.strategies.llm
    import crawler.strategies.static


def crawl_conference(conf: dict, year: int) -> list[CrawlResult]:
    """Crawl a single conference using its configured strategy.

    Returns one CrawlResult per cycle (or one if no cycles).
    """
    _ensure_strategies_loaded()
    strategy = get_strategy(conf["strategy"])
    return strategy.extract(conf, year)


def crawl_all(
    config_path: str = "conferences.yaml",
    years: list[int] | None = None,
    name_filter: str | None = None,
) -> list[CrawlResult]:
    """Crawl all (or filtered) conferences from config.

    Args:
        years: List of target years. Defaults to [current_year] if None.
    """
    import datetime

    if years is None:
        years = [datetime.datetime.now().year]

    _ensure_strategies_loaded()
    conferences = load_conferences(config_path)

    results = []
    for conf in conferences:
        if name_filter and conf["name"].lower() != name_filter.lower():
            continue
        for year in years:
            results.extend(crawl_conference(conf, year))

    return results
