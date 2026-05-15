"""Tests for config loading and strategy dispatch (T2)."""

import tempfile
from pathlib import Path

import pytest
import yaml

from crawler.config import load_conferences, resolve_conf_for_year, resolve_url, ConfigError
from crawler.strategy import get_strategy, _ensure_strategies_loaded


# --- Config loading tests (V7, V8) ---


def _write_conf(entries, tmp_path):
    p = tmp_path / "conferences.yaml"
    p.write_text(yaml.dump(entries))
    return p


def test_load_valid_config(tmp_path):
    entries = [
        {"name": "TestConf", "url": "https://example.com", "strategy": "css", "tags": ["SEC", "TIER1"]},
    ]
    result = load_conferences(_write_conf(entries, tmp_path))
    assert len(result) == 1
    assert result[0]["name"] == "TestConf"


def test_load_real_config():
    """Load the actual conferences.yaml to verify it passes validation."""
    result = load_conferences("conferences.yaml")
    assert len(result) > 0


def test_missing_required_field_v7(tmp_path):
    entries = [
        {"name": "Bad", "url": "https://x.com", "tags": ["SEC"]},  # missing strategy
    ]
    with pytest.raises(ConfigError, match="missing required"):
        load_conferences(_write_conf(entries, tmp_path))


def test_invalid_strategy_v8(tmp_path):
    entries = [
        {"name": "Bad", "url": "https://x.com", "strategy": "magic", "tags": ["SEC"]},
    ]
    with pytest.raises(ConfigError, match="invalid strategy"):
        load_conferences(_write_conf(entries, tmp_path))


def test_not_a_list(tmp_path):
    p = tmp_path / "conferences.yaml"
    p.write_text("name: foo\n")
    with pytest.raises(ConfigError, match="must be a YAML list"):
        load_conferences(p)


def test_file_not_found():
    with pytest.raises(ConfigError, match="not found"):
        load_conferences("/nonexistent/path.yaml")


# --- URL resolution ---


def test_resolve_url_yyyy():
    entry = {"url": "https://conf{YYYY}.org/cfp"}
    assert resolve_url(entry, 2026) == "https://conf2026.org/cfp"


def test_resolve_url_yy():
    entry = {"url": "https://conf.org/{YY}/cfp"}
    assert resolve_url(entry, 2026) == "https://conf.org/26/cfp"


def test_resolve_url_none():
    entry = {"url": None}
    assert resolve_url(entry, 2026) is None


# --- by_year resolution (V13) ---


def test_resolve_conf_no_by_year():
    """Without by_year, returns entry unchanged."""
    entry = {"name": "X", "url": "https://x{YYYY}.org", "strategy": "regex", "tags": ["SEC"]}
    assert resolve_conf_for_year(entry, 2026) is entry


def test_resolve_conf_by_year_merge():
    """Year-specific fields override top-level."""
    entry = {
        "name": "X",
        "strategy": "regex",
        "tags": ["SEC"],
        "selectors": {"section": "old"},
        "by_year": {
            2025: {"url": "https://x2025.org", "selectors": {"section": "new"}},
        },
    }
    merged = resolve_conf_for_year(entry, 2025)
    assert merged["url"] == "https://x2025.org"
    assert merged["selectors"]["section"] == "new"
    assert merged["name"] == "X"  # top-level preserved
    assert "by_year" not in merged  # stripped from result


def test_resolve_conf_by_year_fallback_template():
    """Year not in by_year but url has {YYYY} → returns entry."""
    entry = {
        "name": "X",
        "url": "https://x{YYYY}.org",
        "strategy": "regex",
        "tags": ["SEC"],
        "by_year": {2025: {"url": "https://x2025.org"}},
    }
    result = resolve_conf_for_year(entry, 2026)
    assert result is entry  # fallback to template


def test_resolve_conf_by_year_skip():
    """Year not in by_year and no template → None (skip)."""
    entry = {
        "name": "X",
        "strategy": "regex",
        "tags": ["SEC"],
        "by_year": {2025: {"url": "https://x2025.org"}},
    }
    assert resolve_conf_for_year(entry, 2026) is None


def test_v7_by_year_no_url_valid(tmp_path):
    """V7: entry with by_year but no top-level url should pass validation."""
    entries = [{
        "name": "X",
        "strategy": "regex",
        "tags": ["SEC"],
        "by_year": {2025: {"url": "https://x2025.org"}},
    }]
    result = load_conferences(_write_conf(entries, tmp_path))
    assert len(result) == 1


def test_v7_no_url_no_by_year_invalid(tmp_path):
    """V7: entry with neither url nor by_year should fail."""
    entries = [{"name": "X", "strategy": "regex", "tags": ["SEC"]}]
    with pytest.raises(ConfigError, match="must have 'url' or 'by_year'"):
        load_conferences(_write_conf(entries, tmp_path))


# --- Strategy dispatch ---


def test_all_strategies_registered():
    _ensure_strategies_loaded()
    for name in ("css", "regex", "llm", "static"):
        strategy = get_strategy(name)
        assert strategy.name == name


def test_unknown_strategy_raises():
    with pytest.raises(KeyError, match="Unknown strategy"):
        get_strategy("nonexistent")
