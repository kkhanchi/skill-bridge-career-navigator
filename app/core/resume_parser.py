"""Resume text parsing: extract skills by matching against a taxonomy."""

from __future__ import annotations

import json
import re
from pathlib import Path


def load_taxonomy(path: str = "data/skill_taxonomy.json") -> list[str]:
    """Load the skill taxonomy from a JSON file.

    Returns a list of skill strings (≥50 entries expected).
    """
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_resume(text: str, taxonomy: list[str]) -> list[str]:
    """Extract recognized skills from *text* using case-insensitive word-boundary matching.

    Multi-word skills (e.g. "Machine Learning") are matched as phrases.
    Returns an empty list when nothing is found.
    """
    if not text or not taxonomy:
        return []

    found: list[str] = []
    seen_lower: set[str] = set()

    # Sort taxonomy longest-first so multi-word skills match before sub-words
    for skill in sorted(taxonomy, key=len, reverse=True):
        pattern = r"\b" + re.escape(skill) + r"\b"
        if re.search(pattern, text, re.IGNORECASE):
            key = skill.lower()
            if key not in seen_lower:
                seen_lower.add(key)
                found.append(skill)

    return found
