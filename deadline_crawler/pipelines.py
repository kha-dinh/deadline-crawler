"""Scrapy pipelines for validation and output generation."""

import json
from datetime import datetime, timezone
from pathlib import Path

import yaml
from rich.console import Console
from scrapy.exceptions import DropItem

from crawler.output.generate import (
    LABEL_ORDER,
    _check_date_order,
    _check_v16,
    _check_v20,
    _slugify,
    _validate_entry,
    _validate_entry_warnings,
    transform_entry,
)

_stderr = Console(stderr=True)


def _item_to_entry(item) -> dict:
    """Convert ConferenceItem to generate.py entry shape for validation."""
    entry = {
        "name": item["name"],
        "year": item["year"],
        "link": item["link"],
        "deadline": item.get("deadlines", []),
        "tags": item.get("tags", []),
    }
    if item.get("cycle"):
        entry["cycle"] = item["cycle"]
    if item.get("description"):
        entry["description"] = item["description"]
    if item.get("date"):
        entry["date"] = item["date"]
    if item.get("place"):
        entry["place"] = item["place"]
    if item.get("timezone"):
        entry["timezone"] = item["timezone"]
    if item.get("comment"):
        entry["comment"] = item["comment"]
    return entry


class ValidationPipeline:
    """Validate items against V1-V3, V10, V14, V16, V17, V19, V20, V21.

    Drops invalid items. Logs warnings for soft violations.
    """

    def __init__(self):
        self.strict = False
        self.crawler = None
        self.date_warnings = []  # [(label, warning_str), ...]
        self.missing_warnings = []  # [(label, warning_str), ...]
        self.dropped = []  # [(label, reason), ...]

    @classmethod
    def from_crawler(cls, crawler):
        pipe = cls()
        pipe.crawler = crawler
        pipe.strict = crawler.settings.getbool("STRICT_MODE", False)
        return pipe

    def _inc_stat(self, key):
        if self.crawler:
            self.crawler.stats.inc_value(key)

    def process_item(self, item):
        entry = _item_to_entry(item)
        name = item["name"]
        year = item["year"]
        label = f"{name} {year}"
        if item.get("cycle"):
            label += f" ({item['cycle']})"

        # Hard validation — V1, V2, V3, V10, V17, V19
        errors = _validate_entry(entry)
        if errors:
            reason = "; ".join(errors)
            self.dropped.append((label, reason))
            self._inc_stat("validation/dropped")
            raise DropItem(f"{label}: {reason}")

        # V16: no abstract/submission
        v16 = _check_v16(entry)
        for w in v16:
            self._inc_stat("validation/v16_missing_key_label")
            self.missing_warnings.append((label, w))
        if self.strict and v16:
            raise DropItem(f"V16 violation in {label}")

        # V20: < 2 deadlines
        v20 = _check_v20(entry)
        for w in v20:
            self._inc_stat("validation/v20_few_deadlines")
            self.missing_warnings.append((label, w))
        if self.strict and v20:
            raise DropItem(f"V20 violation in {label}")

        # V21: date year mismatch (warn only)
        for w in _validate_entry_warnings(entry):
            if w not in v16 and w not in v20:
                self._inc_stat("validation/v21_year_mismatch")
                self.date_warnings.append((label, w))

        # V14: date order
        order_issues = _check_date_order(entry)
        for w in order_issues:
            self._inc_stat("validation/v14_date_order")
            self.date_warnings.append((label, w))
        if self.strict and order_issues:
            raise DropItem(f"Date order violation in {label}")

        return item

    def close_spider(self):
        # Collect spider-level errors
        spider = self.crawler.spider if self.crawler else None
        spider_errors = getattr(spider, "errors", []) if spider else []

        has_issues = spider_errors or self.dropped or self.missing_warnings or self.date_warnings
        if not has_issues:
            return

        _stderr.print("")  # blank line before summary

        if spider_errors:
            _stderr.print(f"[bold red]Errors ({len(spider_errors)}):[/]")
            for label, msg in spider_errors:
                _stderr.print(f"  {label}: {msg}")

        if self.dropped:
            _stderr.print(f"[bold red]Skipped ({len(self.dropped)}):[/]")
            for label, reason in self.dropped:
                _stderr.print(f"  {label}: {reason}")

        if self.missing_warnings:
            _stderr.print(f"[bold yellow]Incomplete ({len(self.missing_warnings)}):[/]")
            for label, warning in self.missing_warnings:
                _stderr.print(f"  {label}: {warning}")

        if self.date_warnings:
            _stderr.print(f"[bold yellow]Suspicious dates ({len(self.date_warnings)}):[/]")
            for label, warning in self.date_warnings:
                _stderr.print(f"  {label}: {warning}")


class OutputPipeline:
    """Collect validated items and write JSON/YAML output on spider close."""

    def __init__(self):
        self.items = []
        self.fmt = "json"
        self.output_path = None
        self.diff_baseline = None
        self.change_log = None

    @classmethod
    def from_crawler(cls, crawler):
        pipe = cls()
        pipe.crawler = crawler
        pipe.fmt = crawler.settings.get("OUTPUT_FORMAT", "json")
        pipe.output_path = crawler.settings.get("OUTPUT_PATH")
        pipe.diff_baseline = crawler.settings.get("DIFF_BASELINE")
        pipe.change_log = crawler.settings.get("CHANGE_LOG")
        return pipe

    def process_item(self, item):
        self.items.append(item)
        return item

    def close_spider(self):
        if not self.items:
            _stderr.print("[bold red]No valid items to export[/]")
            return

        now = datetime.now(timezone.utc)
        conferences = []
        for item in self.items:
            entry = _item_to_entry(item)
            conferences.append(transform_entry(entry, now))

        result = {
            "generated_at": now.isoformat(),
            "conferences": conferences,
        }

        output_path = self.output_path or f"output/deadlines.{self.fmt}"
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        if self.fmt == "yaml":
            with open(output_path, "w") as f:
                yaml.dump(result, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        else:
            with open(output_path, "w") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
                f.write("\n")

        _stderr.print(f"Exported {len(conferences)} conference(s) → {output_path}")

        # Diff against baseline if enabled
        if self.diff_baseline:
            from crawler.output.diff import (
                diff_conferences,
                format_changes,
                load_baseline,
                write_changelog,
            )

            baseline = load_baseline(self.diff_baseline)
            changes = diff_conferences(baseline, conferences)
            if changes:
                _stderr.print(f"\n[bold cyan]Changes ({len(changes)}):[/]")
                for line in format_changes(changes):
                    _stderr.print(line)
            else:
                _stderr.print("[dim]No changes from baseline[/]")

            if self.change_log and changes:
                write_changelog(changes, self.change_log)
                _stderr.print(f"[dim]Changelog → {self.change_log}[/]")
