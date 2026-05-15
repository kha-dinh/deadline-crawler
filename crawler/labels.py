"""Label map loader for CFP deadline phrase matching (V10/V11).

All label phrases and skip phrases live in ``labels.yaml`` (project root).
Edit that file directly to add, remove, or override labels.

Module-level ``LABEL_MAP`` and ``_SKIP_PHRASES`` are populated by
``load_label_map()`` on import.
"""

from __future__ import annotations

from pathlib import Path

import yaml


LABEL_MAP: dict[str, list[str]] = {}
_SKIP_PHRASES: frozenset[str] = frozenset()


def load_label_map(path: str | Path | None = None) -> None:
    """Load labels.yaml into LABEL_MAP and _SKIP_PHRASES (in-place).

    path: explicit path, defaults to ``labels.yaml`` in cwd.
    Raises FileNotFoundError if the file does not exist.
    """
    global LABEL_MAP, _SKIP_PHRASES

    labels_path = Path(path) if path else Path("labels.yaml")
    if not labels_path.exists():
        raise FileNotFoundError(f"Label config not found: {labels_path}")

    with open(labels_path) as f:
        data = yaml.safe_load(f) or {}

    skip: list[str] = []
    labels: dict[str, list[str]] = {}

    for key, phrases in data.items():
        if not isinstance(phrases, list):
            continue
        if key == "_skip":
            skip = [str(p) for p in phrases]
        else:
            labels[key] = [str(p) for p in phrases]

    LABEL_MAP = labels
    _SKIP_PHRASES = frozenset(skip)


def _match_label(text: str) -> str | None:
    """Match text against LABEL_MAP, return canonical label or None.

    Longest-match-wins: more specific phrases beat shorter overlapping ones
    (e.g. "author response period ends" beats "author response period").
    Returns None if text contains a _SKIP_PHRASES entry (non-deadline event).
    """
    lower = text.lower()
    if any(skip in lower for skip in _SKIP_PHRASES):
        return None
    best_label = None
    best_len = 0
    for label, phrases in LABEL_MAP.items():
        for phrase in phrases:
            if phrase in lower and len(phrase) > best_len:
                best_label = label
                best_len = len(phrase)
    return best_label


load_label_map()
