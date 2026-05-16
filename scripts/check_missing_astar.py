#!/usr/bin/env python3
"""
Check which A* conferences from CORE 2026 CSV are missing from conferences.yaml.

CSV columns: id, name, acronym, source, rank, in_icore, ...
"""

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CSV_PATH = ROOT / "data" / "core2026.csv"
YAML_PATH = ROOT / "conferences.yaml"


def load_astar_from_csv(path: Path) -> list[dict]:
    results = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) < 5:
                continue
            rank = row[4].strip()
            if rank == "A*":
                results.append({
                    "name": row[1].strip().strip('"'),
                    "acronym": row[2].strip(),
                    "rank": rank,
                })
    return results


def load_yaml_identifiers(path: Path) -> set[str]:
    """Extract all name/core_acronym/acronym-like values from yaml (lowercased)."""
    text = path.read_text(encoding="utf-8")
    identifiers = set()

    # name: <value> — handles both "- name: X" and "  name: X"
    for m in re.finditer(r"^[-\s]*name:\s*(.+)$", text, re.MULTILINE):
        identifiers.add(m.group(1).strip().strip('"').lower())

    # core_acronym: <value>
    for m in re.finditer(r"^\s*core_acronym:\s*(.+)$", text, re.MULTILINE):
        identifiers.add(m.group(1).strip().strip('"').lower())

    # urls often contain the acronym slug — extract from url values too
    for m in re.finditer(r"^\s*url.*:\s*https?://([^./]+)", text, re.MULTILINE):
        identifiers.add(m.group(1).lower())

    return identifiers


def normalize(s: str) -> str:
    return s.lower().replace("-", "").replace(" ", "").replace("_", "")


def is_present(conf: dict, yaml_ids: set[str]) -> bool:
    acronym_norm = normalize(conf["acronym"])
    name_norm = normalize(conf["name"])
    yaml_norms = {normalize(i) for i in yaml_ids}

    # Exact acronym match
    if acronym_norm in yaml_norms:
        return True

    # Exact full name match
    if name_norm in yaml_norms:
        return True

    return False


def main():
    if not CSV_PATH.exists():
        print(f"ERROR: {CSV_PATH} not found", file=sys.stderr)
        sys.exit(1)
    if not YAML_PATH.exists():
        print(f"ERROR: {YAML_PATH} not found", file=sys.stderr)
        sys.exit(1)

    astar = load_astar_from_csv(CSV_PATH)
    yaml_ids = load_yaml_identifiers(YAML_PATH)

    missing = [c for c in astar if not is_present(c, yaml_ids)]
    present = [c for c in astar if is_present(c, yaml_ids)]

    print(f"A* total:   {len(astar)}")
    print(f"In yaml:    {len(present)}")
    print(f"Missing:    {len(missing)}")
    print()

    if missing:
        print("MISSING A* CONFERENCES:")
        for c in sorted(missing, key=lambda x: x["acronym"]):
            print(f"  {c['acronym']:<20} {c['name']}")

    if "--show-present" in sys.argv:
        print()
        print("PRESENT:")
        for c in sorted(present, key=lambda x: x["acronym"]):
            print(f"  {c['acronym']:<20} {c['name']}")


if __name__ == "__main__":
    main()
