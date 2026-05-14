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
    workers: int = 4,
) -> list[CrawlResult]:
    """Crawl all (or filtered) conferences from config.

    Args:
        years: List of target years. Defaults to [current_year] if None.
        workers: Number of parallel threads for fetching. Default 4.
    """
    import datetime
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if years is None:
        years = [datetime.datetime.now().year]

    _ensure_strategies_loaded()
    conferences = load_conferences(config_path)

    # Build work list: (conf, year) pairs
    work = [
        (conf, year)
        for conf in conferences
        if not name_filter or conf["name"].lower() == name_filter.lower()
        for year in years
    ]

    results = []
    warnings = []
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn
    from rich.console import Console

    console = Console(stderr=True)

    def _crawl_one(conf: dict, year: int) -> tuple[list[CrawlResult], list[str]]:
        """Crawl single conference, return (results, warnings)."""
        label = f"{conf['name']} {year}"
        local_results = []
        local_warnings = []
        try:
            conf_results = crawl_conference(conf, year)
            for r in conf_results:
                if not r.deadlines:
                    rlabel = f"{r.name} {r.year} ({r.cycle})" if r.cycle else f"{r.name} {r.year}"
                    local_warnings.append(f"{rlabel}: no deadlines extracted")
                else:
                    local_results.append(r)
        except Exception as e:
            local_warnings.append(f"{label}: {e}")
        return local_results, local_warnings

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("[dim]{task.fields[current]}"),
        console=console,
    ) as progress:
        task = progress.add_task("Crawling", total=len(work), current="")

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_crawl_one, conf, year): f"{conf['name']} {year}"
                for conf, year in work
            }
            for future in as_completed(futures):
                label = futures[future]
                progress.update(task, current=label)
                r, w = future.result()
                results.extend(r)
                warnings.extend(w)
                progress.advance(task)

    if warnings:
        console.print()
        for w in warnings:
            console.print(f"[bold yellow]⚠ {w}[/]")

    return results
