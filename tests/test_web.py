"""Tests for crawler.output — deadlines output generation (T13)."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from crawler.models import CrawlResult
from crawler.output.generate import (
    _slugify, _validate_entry, generate_from_results, generate_output, transform_entry,
)

NOW = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)

VALID_ENTRY = {
    "name": "USENIX Security",
    "year": 2026,
    "description": "USENIX Security Symposium",
    "link": "https://www.usenix.org/conference/usenixsecurity26",
    "deadline": [
        {"label": "submission", "date": "2025-08-26 23:59"},
        {"label": "notification", "date": "2026-02-05 23:59"},
    ],
    "date": "Aug. 12-14",
    "place": "BALTIMORE, MD",
    "tags": ["SEC", "A*"],
    "notification": ["2025-12-04", "2026-05-14"],
}


class TestSlugify:
    def test_simple(self):
        assert _slugify("USENIX Security") == "usenix-security"

    def test_special_chars(self):
        assert _slugify("S&P (Oakland)") == "s-p-oakland"

    def test_strips_edges(self):
        assert _slugify("  CCS  ") == "ccs"


class TestValidateEntry:
    def test_valid(self):
        assert _validate_entry(VALID_ENTRY) == []

    def test_missing_name(self):
        entry = {**VALID_ENTRY, "name": ""}
        errors = _validate_entry(entry)
        assert any("missing name" in e for e in errors)

    def test_missing_deadline(self):
        entry = {**VALID_ENTRY, "deadline": []}
        errors = _validate_entry(entry)
        assert any("missing deadline" in e for e in errors)

    def test_bad_deadline_format(self):
        entry = {**VALID_ENTRY, "deadline": [{"label": "submission", "date": "2025-08-26"}]}
        errors = _validate_entry(entry)
        assert any("bad deadline date format" in e for e in errors)

    def test_bad_deadline_label(self):
        entry = {**VALID_ENTRY, "deadline": [{"label": "bogus", "date": "2025-08-26 23:59"}]}
        errors = _validate_entry(entry)
        assert any("bad deadline label" in e for e in errors)

    def test_deadline_not_dict(self):
        entry = {**VALID_ENTRY, "deadline": ["2025-08-26 23:59"]}
        errors = _validate_entry(entry)
        assert any("deadline must be dict" in e for e in errors)

    def test_bad_area_code(self):
        entry = {**VALID_ENTRY, "tags": ["INVALID", "A*"]}
        errors = _validate_entry(entry)
        assert any("bad area code" in e for e in errors)

    def test_bad_tier(self):
        entry = {**VALID_ENTRY, "tags": ["SEC", "TIER3"]}
        errors = _validate_entry(entry)
        assert any("bad core rank" in e for e in errors)

    def test_insufficient_tags(self):
        entry = {**VALID_ENTRY, "tags": ["SEC"]}
        errors = _validate_entry(entry)
        assert any("tags need" in e for e in errors)


class TestTransformEntry:
    def test_output_shape(self):
        result = transform_entry(VALID_ENTRY, NOW)
        required_keys = {
            "id", "name", "year", "description", "link",
            "area", "tier", "place", "date", "timezone",
            "deadlines", "tags",
        }
        assert required_keys <= set(result.keys())

    def test_id_is_slug(self):
        result = transform_entry(VALID_ENTRY, NOW)
        assert result["id"] == "usenix-security-2026"

    def test_area_tier_from_tags(self):
        result = transform_entry(VALID_ENTRY, NOW)
        assert result["area"] == "SEC"
        assert result["tier"] == "A*"

    def test_timezone_defaults_aoe(self):
        result = transform_entry(VALID_ENTRY, NOW)
        assert result["timezone"] == "AoE"

    def test_timezone_override(self):
        entry = {**VALID_ENTRY, "timezone": "UTC"}
        result = transform_entry(entry, NOW)
        assert result["timezone"] == "UTC"

    def test_passed_flag(self):
        result = transform_entry(VALID_ENTRY, NOW)
        # 2025-08-26 is past relative to 2026-05-14
        assert result["deadlines"][0]["passed"] is True
        # 2026-02-05 is also past relative to 2026-05-14
        assert result["deadlines"][1]["passed"] is True

    def test_future_deadline_not_passed(self):
        entry = {**VALID_ENTRY, "deadline": [{"label": "submission", "date": "2027-01-01 23:59"}]}
        result = transform_entry(entry, NOW)
        assert result["deadlines"][0]["passed"] is False

    def test_deadline_labels(self):
        result = transform_entry(VALID_ENTRY, NOW)
        assert result["deadlines"][0]["label"] == "submission"
        assert result["deadlines"][1]["label"] == "notification"

    def test_single_deadline_label(self):
        entry = {**VALID_ENTRY, "deadline": [{"label": "submission", "date": "2025-08-26 23:59"}]}
        result = transform_entry(entry, NOW)
        assert result["deadlines"][0]["label"] == "submission"

    def test_comment_included_when_present(self):
        entry = {**VALID_ENTRY, "comment": "Paper due soon"}
        result = transform_entry(entry, NOW)
        assert result["comment"] == "Paper due soon"

    def test_comment_absent_when_not_set(self):
        result = transform_entry(VALID_ENTRY, NOW)
        assert "comment" not in result


class TestGenerateOutput:
    def test_full_roundtrip(self, tmp_path):
        data_file = tmp_path / "data.yaml"
        out_file = tmp_path / "deadlines.json"
        with open(data_file, "w") as f:
            yaml.dump([VALID_ENTRY], f)

        result = generate_output(data_file, out_file, fmt="json", now=NOW)

        assert "generated_at" in result
        assert len(result["conferences"]) == 1
        assert result["conferences"][0]["name"] == "USENIX Security 2026"

        # Verify file written
        with open(out_file) as f:
            from_disk = json.load(f)
        assert from_disk == result

    def test_invalid_entry_raises(self, tmp_path):
        data_file = tmp_path / "data.yaml"
        bad = {"name": "", "year": 2026, "link": "", "deadline": [], "tags": []}
        with open(data_file, "w") as f:
            yaml.dump([bad], f)

        with pytest.raises(ValueError, match="Invalid entry"):
            generate_output(data_file, tmp_path / "out.json", now=NOW)

    def test_yaml_roundtrip(self, tmp_path):
        data_file = tmp_path / "data.yaml"
        out_file = tmp_path / "deadlines.yaml"
        with open(data_file, "w") as f:
            yaml.dump([VALID_ENTRY], f)

        result = generate_output(data_file, out_file, fmt="yaml", now=NOW)

        with open(out_file) as f:
            from_disk = yaml.safe_load(f)
        assert from_disk["generated_at"] == result["generated_at"]
        assert len(from_disk["conferences"]) == 1
        assert from_disk["conferences"][0]["name"] == "USENIX Security 2026"

    def test_invalid_format_raises(self, tmp_path):
        data_file = tmp_path / "data.yaml"
        with open(data_file, "w") as f:
            yaml.dump([VALID_ENTRY], f)

        with pytest.raises(ValueError, match="Unsupported format"):
            generate_output(data_file, tmp_path / "out.xml", fmt="xml", now=NOW)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            generate_output(tmp_path / "nope.yaml", tmp_path / "out.json")


class TestGenerateFromResults:
    def test_basic(self, tmp_path):
        results = [
            CrawlResult(
                name="USENIX Security",
                year=2026,
                link="https://example.com",
                deadlines=[{"label": "submission", "date": "2025-08-26 23:59"}],
                tags=["SEC", "A*"],
                description="USENIX Security Symposium",
            ),
        ]
        out = tmp_path / "deadlines.json"
        data = generate_from_results(results, out, fmt="json", now=NOW)
        assert len(data["conferences"]) == 1
        assert data["conferences"][0]["name"] == "USENIX Security 2026"
        assert out.exists()

    def test_cycle_name(self, tmp_path):
        results = [
            CrawlResult(
                name="USENIX Security",
                year=2026,
                link="https://example.com",
                deadlines=[{"label": "submission", "date": "2025-08-26 23:59"}],
                tags=["SEC", "A*"],
                cycle="Cycle 1",
            ),
        ]
        out = tmp_path / "deadlines.json"
        data = generate_from_results(results, out, fmt="json", now=NOW)
        assert data["conferences"][0]["name"] == "USENIX Security 2026 (Cycle 1)"

    def test_skips_invalid(self, tmp_path):
        results = [
            CrawlResult(name="Bad", year=2026, link="", deadlines=[], tags=[]),
            CrawlResult(
                name="Good",
                year=2026,
                link="https://example.com",
                deadlines=[{"label": "submission", "date": "2025-08-26 23:59"}],
                tags=["SEC", "A*"],
            ),
        ]
        out = tmp_path / "deadlines.json"
        data = generate_from_results(results, out, fmt="json", now=NOW)
        assert len(data["conferences"]) == 1
        assert data["conferences"][0]["name"] == "Good 2026"
