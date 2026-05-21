"""Tests for validate command (T10) and terminal table (T11)."""

import json
import pytest
from datetime import datetime, timezone
from pathlib import Path

from main import cmd_validate, _output_to_entry, print_table, _days_until, _urgency_color
from crawler.output.generate import _check_date_order, _validate_entry, _validate_entry_warnings


# --- T10: validate ---


def _make_valid_conf():
    return {
        "id": "test-conf",
        "name": "Test Conf",
        "year": 2026,
        "link": "https://example.com",
        "area": "SEC",
        "rank": "A*",
        "deadlines": [{"label": "submission", "date": "2026-06-01 23:59"}],
    }


def test_output_to_entry_shape():
    conf = _make_valid_conf()
    entry = _output_to_entry(conf)
    assert entry["name"] == "Test Conf"
    assert entry["year"] == 2026
    assert entry["link"] == "https://example.com"
    assert len(entry["deadline"]) == 1
    assert entry["deadline"][0]["label"] == "submission"
    assert entry["area"] == "SEC"
    assert entry["rank"] == "A*"


def test_validate_valid_file(tmp_path, capsys):
    data = {"conferences": [_make_valid_conf()]}
    f = tmp_path / "test.json"
    f.write_text(json.dumps(data))

    class Args:
        input = str(f)
        strict = False

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
        strict = False

    with pytest.raises(SystemExit):
        cmd_validate(Args())
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "bad deadline label" in combined


def test_validate_duplicate_detection(tmp_path, capsys):
    conf = _make_valid_conf()
    data = {"conferences": [conf, conf]}
    f = tmp_path / "test.json"
    f.write_text(json.dumps(data))

    class Args:
        input = str(f)
        strict = False

    with pytest.raises(SystemExit):
        cmd_validate(Args())
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "duplicate" in combined


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
    assert _urgency_color(-5) == "\033[2m"


def test_print_table_output(capsys):
    now = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    conferences = [
        {
            "name": "ConfA",
            "year": 2026,
            "area": "SEC",
            "rank": "A*",
            "deadlines": [
                {"label": "submission", "date": "2026-01-05 23:59"},
            ],
        },
        {
            "name": "ConfB",
            "year": 2026,
            "area": "SYS",
            "rank": "A",
            "deadlines": [
                {"label": "abstract", "date": "2026-02-15 23:59"},
            ],
        },
    ]
    print_table(conferences, now=now)
    out = capsys.readouterr().out
    assert "ConfA" in out
    assert "ConfB" in out
    assert "submission" in out
    assert "abstract" in out


# --- V14: date order checks ---


def test_check_date_order_valid():
    """V14: correctly ordered dates produce no warnings."""
    entry = {
        "deadline": [
            {"label": "abstract", "date": "2026-01-10 23:59"},
            {"label": "submission", "date": "2026-01-20 23:59"},
            {"label": "notification", "date": "2026-03-01 23:59"},
            {"label": "camera_ready", "date": "2026-04-01 23:59"},
        ]
    }
    assert _check_date_order(entry) == []


def test_check_date_order_violation():
    """V14: out-of-order dates produce warnings."""
    entry = {
        "deadline": [
            {"label": "abstract", "date": "2026-02-01 23:59"},
            {"label": "submission", "date": "2026-01-15 23:59"},  # before abstract
        ]
    }
    warnings = _check_date_order(entry)
    assert len(warnings) == 1
    assert "abstract" in warnings[0]
    assert "submission" in warnings[0]


def test_check_date_order_single_deadline():
    """V14: single deadline = nothing to compare, no warnings."""
    entry = {"deadline": [{"label": "submission", "date": "2026-06-01 23:59"}]}
    assert _check_date_order(entry) == []


def test_check_date_order_equal_dates():
    """V14: equal dates are allowed (≤ not <)."""
    entry = {
        "deadline": [
            {"label": "abstract", "date": "2026-01-15 23:59"},
            {"label": "submission", "date": "2026-01-15 23:59"},
        ]
    }
    assert _check_date_order(entry) == []


# --- V17: duplicate labels ---


def test_v17_duplicate_label_error():
    """V17: same label twice in one entry → error."""
    entry = {
        "name": "Conf", "year": 2026, "link": "https://example.com",
        "area": "SEC", "rank": "A*",
        "deadline": [
            {"label": "submission", "date": "2026-06-01 23:59"},
            {"label": "submission", "date": "2026-07-01 23:59"},
        ],
    }
    errors = _validate_entry(entry)
    assert any("duplicate deadline label" in e for e in errors)


def test_v17_no_duplicate_ok():
    """V17: distinct labels → no duplicate error."""
    entry = {
        "name": "Conf", "year": 2026, "link": "https://example.com",
        "area": "SEC", "rank": "A*",
        "deadline": [
            {"label": "abstract", "date": "2026-05-01 23:59"},
            {"label": "submission", "date": "2026-06-01 23:59"},
        ],
    }
    errors = _validate_entry(entry)
    assert not any("duplicate" in e for e in errors)


# --- V19: URL validation ---


def test_v19_valid_https_url():
    """V19: valid HTTPS URL → no error."""
    entry = {
        "name": "Conf", "year": 2026, "link": "https://conf.example.com/2026",
        "area": "SEC", "rank": "A*",
        "deadline": [{"label": "submission", "date": "2026-06-01 23:59"}],
    }
    errors = _validate_entry(entry)
    assert not any("link" in e for e in errors)


def test_v19_valid_http_url():
    """V19: plain HTTP URL → no error."""
    entry = {
        "name": "Conf", "year": 2026, "link": "http://conf.example.com/cfp",
        "area": "SEC", "rank": "A*",
        "deadline": [{"label": "submission", "date": "2026-06-01 23:59"}],
    }
    errors = _validate_entry(entry)
    assert not any("link must be" in e for e in errors)


def test_v19_missing_link():
    """V19: empty link → missing link error."""
    entry = {
        "name": "Conf", "year": 2026, "link": "",
        "area": "SEC", "rank": "A*",
        "deadline": [{"label": "submission", "date": "2026-06-01 23:59"}],
    }
    errors = _validate_entry(entry)
    assert any("missing link" in e for e in errors)


def test_v19_non_http_scheme():
    """V19: ftp:// URL → error."""
    entry = {
        "name": "Conf", "year": 2026, "link": "ftp://example.com/cfp",
        "area": "SEC", "rank": "A*",
        "deadline": [{"label": "submission", "date": "2026-06-01 23:59"}],
    }
    errors = _validate_entry(entry)
    assert any("link must be HTTP/HTTPS" in e for e in errors)


def test_v19_no_scheme():
    """V19: bare path → error."""
    entry = {
        "name": "Conf", "year": 2026, "link": "example.com/cfp",
        "area": "SEC", "rank": "A*",
        "deadline": [{"label": "submission", "date": "2026-06-01 23:59"}],
    }
    errors = _validate_entry(entry)
    assert any("link must be HTTP/HTTPS" in e for e in errors)


# --- V16: no abstract/submission warning ---


def test_v16_warn_no_abstract_or_submission():
    """V16: entry with only notification → warn."""
    entry = {
        "name": "Conf", "year": 2026, "link": "https://example.com",
        "area": "SEC", "rank": "A*",
        "deadline": [{"label": "notification", "date": "2026-08-01 23:59"}],
    }
    warnings = _validate_entry_warnings(entry)
    assert any("no abstract or submission" in w for w in warnings)


def test_v16_no_warn_has_submission():
    """V16: entry with submission → no V16 warning."""
    entry = {
        "name": "Conf", "year": 2026, "link": "https://example.com",
        "area": "SEC", "rank": "A*",
        "deadline": [{"label": "submission", "date": "2026-06-01 23:59"}],
    }
    warnings = _validate_entry_warnings(entry)
    assert not any("no abstract or submission" in w for w in warnings)


def test_v16_no_warn_has_abstract():
    """V16: entry with abstract → no V16 warning."""
    entry = {
        "name": "Conf", "year": 2026, "link": "https://example.com",
        "area": "SEC", "rank": "A*",
        "deadline": [
            {"label": "abstract", "date": "2026-05-01 23:59"},
            {"label": "notification", "date": "2026-08-01 23:59"},
        ],
    }
    warnings = _validate_entry_warnings(entry)
    assert not any("no abstract or submission" in w for w in warnings)


# --- V20: single deadline warning ---


def test_v20_warn_single_deadline():
    """V20: exactly 1 deadline → warn."""
    entry = {
        "name": "Conf", "year": 2026, "link": "https://example.com",
        "area": "SEC", "rank": "A*",
        "deadline": [{"label": "submission", "date": "2026-06-01 23:59"}],
    }
    warnings = _validate_entry_warnings(entry)
    assert any("only 1 deadline" in w for w in warnings)


def test_v20_no_warn_multiple_deadlines():
    """V20: 2+ deadlines → no V20 warning."""
    entry = {
        "name": "Conf", "year": 2026, "link": "https://example.com",
        "area": "SEC", "rank": "A*",
        "deadline": [
            {"label": "abstract", "date": "2026-05-01 23:59"},
            {"label": "submission", "date": "2026-06-01 23:59"},
        ],
    }
    warnings = _validate_entry_warnings(entry)
    assert not any("only 1 deadline" in w for w in warnings)


# --- V21: date field year must match entry year ---


def test_v21_warn_year_mismatch():
    """V21: date field contains wrong year → warn."""
    entry = {
        "name": "Conf", "year": 2026, "link": "https://example.com",
        "area": "SEC", "rank": "A*",
        "deadline": [{"label": "submission", "date": "2026-06-01 23:59"},
                     {"label": "abstract", "date": "2026-05-01 23:59"}],
        "date": "July 7–9, 2025",
    }
    warnings = _validate_entry_warnings(entry)
    assert any("date field year" in w for w in warnings)


def test_v21_no_warn_year_match():
    """V21: date field year matches entry year → no warning."""
    entry = {
        "name": "Conf", "year": 2026, "link": "https://example.com",
        "area": "SEC", "rank": "A*",
        "deadline": [{"label": "submission", "date": "2026-06-01 23:59"},
                     {"label": "abstract", "date": "2026-05-01 23:59"}],
        "date": "November 15-18, 2026",
    }
    warnings = _validate_entry_warnings(entry)
    assert not any("date field year" in w for w in warnings)


def test_v21_no_warn_empty_date():
    """V21: empty date field → no warning."""
    entry = {
        "name": "Conf", "year": 2026, "link": "https://example.com",
        "area": "SEC", "rank": "A*",
        "deadline": [{"label": "submission", "date": "2026-06-01 23:59"},
                     {"label": "abstract", "date": "2026-05-01 23:59"}],
        "date": "",
    }
    warnings = _validate_entry_warnings(entry)
    assert not any("date field year" in w for w in warnings)


def test_print_table_sort_by_urgency(capsys):
    """Soonest deadline first."""
    now = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    conferences = [
        {
            "name": "Later",
            "year": 2026,
            "area": "SEC",
            "rank": "A*",
            "deadlines": [{"label": "submission", "date": "2026-06-01 23:59"}],
        },
        {
            "name": "Sooner",
            "year": 2026,
            "area": "SYS",
            "rank": "A*",
            "deadlines": [{"label": "submission", "date": "2026-01-03 23:59"}],
        },
    ]
    print_table(conferences, now=now)
    out = capsys.readouterr().out
    sooner_pos = out.index("Sooner")
    later_pos = out.index("Later")
    assert sooner_pos < later_pos
