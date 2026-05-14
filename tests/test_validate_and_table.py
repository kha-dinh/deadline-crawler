"""Tests for validate command (T10) and terminal table (T11)."""

import json
import pytest
from datetime import datetime, timezone
from pathlib import Path

from main import cmd_validate, _output_to_entry, print_table, _days_until, _urgency_color


# --- T10: validate ---


def _make_valid_conf():
    return {
        "id": "test-conf",
        "name": "Test Conf",
        "year": 2026,
        "link": "https://example.com",
        "area": "SEC",
        "tier": "TIER1",
        "deadlines": [{"label": "submission", "date": "2026-06-01 23:59", "passed": False}],
        "tags": ["SEC", "TIER1"],
    }


def test_output_to_entry_shape():
    conf = _make_valid_conf()
    entry = _output_to_entry(conf)
    assert entry["name"] == "Test Conf"
    assert entry["year"] == 2026
    assert entry["link"] == "https://example.com"
    assert len(entry["deadline"]) == 1
    assert entry["deadline"][0]["label"] == "submission"
    assert entry["tags"] == ["SEC", "TIER1"]


def test_validate_valid_file(tmp_path, capsys):
    data = {"conferences": [_make_valid_conf()]}
    f = tmp_path / "test.json"
    f.write_text(json.dumps(data))

    class Args:
        input = str(f)

    cmd_validate(Args())
    out = capsys.readouterr().out
    assert "1 conference(s) valid" in out


def test_validate_invalid_file(tmp_path, capsys):
    bad_conf = _make_valid_conf()
    bad_conf["deadlines"][0]["label"] = "bogus_label"
    data = {"conferences": [bad_conf]}
    f = tmp_path / "test.json"
    f.write_text(json.dumps(data))

    class Args:
        input = str(f)

    with pytest.raises(SystemExit):
        cmd_validate(Args())
    out = capsys.readouterr().out
    assert "bad deadline label" in out


def test_validate_duplicate_detection(tmp_path, capsys):
    conf = _make_valid_conf()
    data = {"conferences": [conf, conf]}
    f = tmp_path / "test.json"
    f.write_text(json.dumps(data))

    class Args:
        input = str(f)

    with pytest.raises(SystemExit):
        cmd_validate(Args())
    out = capsys.readouterr().out
    assert "duplicate" in out


# --- T11: table + color ---


def test_days_until_future():
    now = datetime(2026, 1, 1, 0, 0)
    assert _days_until("2026-01-08 23:59", now) == 7


def test_days_until_past():
    now = datetime(2026, 1, 10, 0, 0)
    assert _days_until("2026-01-08 23:59", now) < 0


def test_urgency_color_red():
    color = _urgency_color(3)
    assert "\033[31m" in color


def test_urgency_color_yellow():
    color = _urgency_color(15)
    assert "\033[33m" in color


def test_urgency_color_green():
    color = _urgency_color(60)
    assert "\033[32m" in color


def test_urgency_color_past():
    assert _urgency_color(-5) == ""


def test_print_table_output(capsys):
    now = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    conferences = [
        {
            "name": "ConfA",
            "year": 2026,
            "area": "SEC",
            "tier": "TIER1",
            "deadlines": [
                {"label": "submission", "date": "2026-01-05 23:59", "passed": False},
            ],
        },
        {
            "name": "ConfB",
            "year": 2026,
            "area": "SYS",
            "tier": "TIER2",
            "deadlines": [
                {"label": "abstract", "date": "2026-02-15 23:59", "passed": False},
            ],
        },
    ]
    print_table(conferences, now=now)
    out = capsys.readouterr().out
    assert "ConfA" in out
    assert "ConfB" in out
    assert "submission" in out
    assert "abstract" in out


def test_print_table_sort_by_urgency(capsys):
    """Soonest deadline first."""
    now = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    conferences = [
        {
            "name": "Later",
            "year": 2026,
            "area": "SEC",
            "tier": "TIER1",
            "deadlines": [{"label": "submission", "date": "2026-06-01 23:59", "passed": False}],
        },
        {
            "name": "Sooner",
            "year": 2026,
            "area": "SYS",
            "tier": "TIER1",
            "deadlines": [{"label": "submission", "date": "2026-01-03 23:59", "passed": False}],
        },
    ]
    print_table(conferences, now=now)
    out = capsys.readouterr().out
    sooner_pos = out.index("Sooner")
    later_pos = out.index("Later")
    assert sooner_pos < later_pos
