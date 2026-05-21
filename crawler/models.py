"""Data models for crawl results."""

from dataclasses import dataclass, field


@dataclass
class CrawlResult:
    """Result of crawling a single conference (or one cycle of it)."""

    name: str
    year: int
    link: str
    deadlines: list[dict] = field(default_factory=list)  # [{label: str, date: str}]
    cycle: str | None = None
    date: str | None = None
    place: str | None = None
    description: str | None = None
    area: str = ""
    rank: str = "unknown"
    notification: list[str] = field(default_factory=list)
    timezone: str | None = None
    comment: str | None = None
