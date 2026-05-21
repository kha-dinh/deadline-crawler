"""Tests for crawler.output.diff — change detection between crawl runs."""

import json
import tempfile
from pathlib import Path

from crawler.output.diff import Change, diff_conferences, format_changes, load_baseline, write_changelog


def _conf(id, name, deadlines):
    """Helper to build a conference entry in output shape."""
    return {
        "id": id,
        "name": name,
        "year": 2026,
        "deadlines": [{"label": l, "date": d} for l, d in deadlines],
    }


class TestDiffConferences:
    def test_no_changes(self):
        old = [_conf("ccs-2026", "CCS 2026", [("submission", "2026-03-15 23:59")])]
        new = [_conf("ccs-2026", "CCS 2026", [("submission", "2026-03-15 23:59")])]
        assert diff_conferences(old, new) == []

    def test_added_conference(self):
        old = []
        new = [_conf("ccs-2026", "CCS 2026", [("submission", "2026-03-15 23:59")])]
        changes = diff_conferences(old, new)
        assert len(changes) == 1
        assert changes[0].type == "added"
        assert changes[0].conf_id == "ccs-2026"

    def test_removed_conference(self):
        old = [_conf("ccs-2026", "CCS 2026", [("submission", "2026-03-15 23:59")])]
        new = []
        changes = diff_conferences(old, new)
        assert len(changes) == 1
        assert changes[0].type == "removed"
        assert changes[0].conf_id == "ccs-2026"

    def test_deadline_changed(self):
        old = [_conf("ccs-2026", "CCS 2026", [("submission", "2026-03-15 23:59")])]
        new = [_conf("ccs-2026", "CCS 2026", [("submission", "2026-03-20 23:59")])]
        changes = diff_conferences(old, new)
        assert len(changes) == 1
        c = changes[0]
        assert c.type == "deadline_changed"
        assert c.label == "submission"
        assert c.old == "2026-03-15 23:59"
        assert c.new == "2026-03-20 23:59"

    def test_deadline_added(self):
        old = [_conf("ccs-2026", "CCS 2026", [("submission", "2026-03-15 23:59")])]
        new = [_conf("ccs-2026", "CCS 2026", [
            ("submission", "2026-03-15 23:59"),
            ("notification", "2026-06-01 23:59"),
        ])]
        changes = diff_conferences(old, new)
        assert len(changes) == 1
        assert changes[0].type == "deadline_added"
        assert changes[0].label == "notification"

    def test_deadline_removed(self):
        old = [_conf("ccs-2026", "CCS 2026", [
            ("submission", "2026-03-15 23:59"),
            ("notification", "2026-06-01 23:59"),
        ])]
        new = [_conf("ccs-2026", "CCS 2026", [("submission", "2026-03-15 23:59")])]
        changes = diff_conferences(old, new)
        assert len(changes) == 1
        assert changes[0].type == "deadline_removed"
        assert changes[0].label == "notification"

    def test_multiple_changes(self):
        old = [
            _conf("ccs-2026", "CCS 2026", [("submission", "2026-03-15 23:59")]),
            _conf("sosp-2025", "SOSP 2025", [("submission", "2025-04-10 23:59")]),
        ]
        new = [
            _conf("ccs-2026", "CCS 2026", [("submission", "2026-03-20 23:59")]),
            _conf("ndss-2027", "NDSS 2027", [("submission", "2027-01-10 23:59")]),
        ]
        changes = diff_conferences(old, new)
        types = {c.type for c in changes}
        assert "added" in types  # ndss-2027
        assert "removed" in types  # sosp-2025
        assert "deadline_changed" in types  # ccs submission date

    def test_empty_both(self):
        assert diff_conferences([], []) == []


class TestLoadBaseline:
    def test_missing_file(self):
        assert load_baseline("/nonexistent/path.json") == []

    def test_load_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "generated_at": "2026-05-19T00:00:00",
                "conferences": [{"id": "test", "name": "Test"}],
            }, f)
            f.flush()
            result = load_baseline(f.name)
        assert len(result) == 1
        assert result[0]["id"] == "test"
        Path(f.name).unlink()


class TestFormatChanges:
    def test_format_added(self):
        changes = [Change(type="added", conf_id="x", conf_name="X 2026")]
        lines = format_changes(changes)
        assert "+" in lines[0]
        assert "X 2026" in lines[0]

    def test_format_deadline_changed(self):
        changes = [Change(
            type="deadline_changed", conf_id="x", conf_name="X 2026",
            label="submission", old="2026-03-15 23:59", new="2026-03-20 23:59")]
        lines = format_changes(changes)
        assert "submission" in lines[0]
        assert "->" in lines[0]


class TestWriteChangelog:
    def test_writes_jsonl(self):
        changes = [
            Change(type="added", conf_id="x", conf_name="X 2026"),
            Change(type="deadline_changed", conf_id="y", conf_name="Y 2026",
                   label="submission", old="old", new="new"),
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        write_changelog(changes, path)
        lines = Path(path).read_text().strip().split("\n")
        assert len(lines) == 2
        entry = json.loads(lines[0])
        assert entry["type"] == "added"
        assert "timestamp" in entry
        Path(path).unlink()
