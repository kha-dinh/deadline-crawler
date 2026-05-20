"""Diff engine for conference deadline change detection."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Change:
    """A single detected change between baseline and current crawl."""

    type: str  # "added" | "removed" | "deadline_changed" | "deadline_added" | "deadline_removed"
    conf_id: str
    conf_name: str
    label: str | None = None  # deadline label, None for conf-level changes
    old: str | None = None
    new: str | None = None


def diff_conferences(old: list[dict], new: list[dict]) -> list[Change]:
    """Compare two conference lists (output shape from transform_entry).

    Each entry must have 'id', 'name', and 'deadlines' (list of {label, date}).
    Returns list of Change objects describing differences.
    """
    old_by_id = {c["id"]: c for c in old}
    new_by_id = {c["id"]: c for c in new}

    changes: list[Change] = []

    # Added conferences
    for cid, conf in new_by_id.items():
        if cid not in old_by_id:
            changes.append(Change(
                type="added",
                conf_id=cid,
                conf_name=conf.get("name", cid),
            ))

    # Removed conferences
    for cid, conf in old_by_id.items():
        if cid not in new_by_id:
            changes.append(Change(
                type="removed",
                conf_id=cid,
                conf_name=conf.get("name", cid),
            ))

    # Modified conferences — compare deadlines
    for cid in sorted(set(old_by_id) & set(new_by_id)):
        old_conf = old_by_id[cid]
        new_conf = new_by_id[cid]
        name = new_conf.get("name", cid)

        old_dl = {d["label"]: d["date"] for d in old_conf.get("deadlines", [])}
        new_dl = {d["label"]: d["date"] for d in new_conf.get("deadlines", [])}

        for label in sorted(set(new_dl) - set(old_dl)):
            changes.append(Change(
                type="deadline_added",
                conf_id=cid,
                conf_name=name,
                label=label,
                new=new_dl[label],
            ))

        for label in sorted(set(old_dl) - set(new_dl)):
            changes.append(Change(
                type="deadline_removed",
                conf_id=cid,
                conf_name=name,
                label=label,
                old=old_dl[label],
            ))

        for label in sorted(set(old_dl) & set(new_dl)):
            if old_dl[label] != new_dl[label]:
                changes.append(Change(
                    type="deadline_changed",
                    conf_id=cid,
                    conf_name=name,
                    label=label,
                    old=old_dl[label],
                    new=new_dl[label],
                ))

    return changes


def load_baseline(path: str) -> list[dict]:
    """Load baseline output file, return conferences list."""
    p = Path(path)
    if not p.exists():
        return []
    with open(p) as f:
        if p.suffix == ".yaml" or p.suffix == ".yml":
            import yaml
            data = yaml.safe_load(f)
        else:
            data = json.load(f)
    return data.get("conferences", [])


def format_changes(changes: list[Change]) -> list[str]:
    """Format changes as human-readable lines."""
    lines = []
    for c in changes:
        if c.type == "added":
            lines.append(f"  + {c.conf_name} (new)")
        elif c.type == "removed":
            lines.append(f"  - {c.conf_name} (removed)")
        elif c.type == "deadline_changed":
            lines.append(f"  ~ {c.conf_name} {c.label}: {c.old} -> {c.new}")
        elif c.type == "deadline_added":
            lines.append(f"  + {c.conf_name} {c.label}: {c.new}")
        elif c.type == "deadline_removed":
            lines.append(f"  - {c.conf_name} {c.label}: {c.old} (removed)")
    return lines


def write_changelog(changes: list[Change], path: str) -> None:
    """Append changes as JSONL to changelog file."""
    ts = datetime.now(timezone.utc).isoformat()
    with open(path, "a") as f:
        for c in changes:
            entry = {"timestamp": ts, **asdict(c)}
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
