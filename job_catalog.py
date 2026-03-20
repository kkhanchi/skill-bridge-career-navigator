"""Job catalog: load, validate, and search synthetic job postings."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from models import JobPosting

logger = logging.getLogger(__name__)

_REQUIRED_FIELDS = {"title", "description", "required_skills", "preferred_skills", "experience_level"}


def load_jobs(path: str = "data/jobs.json") -> list[JobPosting]:
    """Load and validate job postings from a JSON file.

    Skips malformed entries (logs a warning for each).
    Raises ``FileNotFoundError`` if the file does not exist.
    """
    if not Path(path).exists():
        raise FileNotFoundError(f"Job catalog file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    jobs: list[JobPosting] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            logger.warning("Job entry %d is not a dict — skipped", i)
            continue

        missing = _REQUIRED_FIELDS - entry.keys()
        if missing:
            logger.warning("Job entry %d missing fields %s — skipped", i, missing)
            continue

        # Basic type checks
        if (
            not isinstance(entry["title"], str)
            or not isinstance(entry["description"], str)
            or not isinstance(entry["required_skills"], list)
            or not isinstance(entry["preferred_skills"], list)
            or not isinstance(entry["experience_level"], str)
        ):
            logger.warning("Job entry %d has invalid field types — skipped", i)
            continue

        jobs.append(
            JobPosting(
                title=entry["title"],
                description=entry["description"],
                required_skills=entry["required_skills"],
                preferred_skills=entry["preferred_skills"],
                experience_level=entry["experience_level"],
            )
        )

    return jobs


def search_jobs(
    jobs: list[JobPosting],
    keyword: str = "",
    skill: str = "",
) -> list[JobPosting]:
    """Filter jobs by title keyword and/or required skill (case-insensitive).

    If both *keyword* and *skill* are provided, a job must match **either** filter.
    Returns all jobs when both filters are empty.
    """
    if not keyword and not skill:
        return list(jobs)

    kw_lower = keyword.strip().lower()
    sk_lower = skill.strip().lower()
    results: list[JobPosting] = []

    for job in jobs:
        match = False
        if kw_lower and kw_lower in job.title.lower():
            match = True
        if sk_lower and any(s.lower() == sk_lower for s in job.required_skills):
            match = True
        if match:
            results.append(job)

    return results
