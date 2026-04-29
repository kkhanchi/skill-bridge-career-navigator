"""In-memory :class:`JobRepository`: stable slug IDs + paginated filtering.

Job data is loaded once at app startup. Each :class:`JobPosting` is
wrapped in a :class:`JobRecord` with a slug id derived from the title;
collisions are disambiguated in load order with ``-2``, ``-3`` suffixes
(R3.6). Slugs are stable across restarts as long as ``jobs.json`` is
stable.

Filtering delegates to :func:`core.job_catalog.search_jobs` so the API
and the Streamlit UI share exactly one implementation (ADR-003 seam).

Design reference: `.kiro/specs/phase-1-rest-api/design.md` §Job IDs.
Requirement reference: R3.1, R3.2, R3.4, R3.5, R3.6, R11.2.
"""

from __future__ import annotations

import re
from math import ceil

from app.core.job_catalog import search_jobs
from app.core.models import JobPosting
from app.repositories.base import JobRecord


_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def _slugify(title: str) -> str:
    """Produce a lowercase, hyphenated slug from a free-form title.

    "Backend Developer" -> "backend-developer"
    "Sr. ML / AI Engineer" -> "sr-ml-ai-engineer"
    """
    lowered = title.lower().strip()
    slug = _SLUG_STRIP.sub("-", lowered).strip("-")
    return slug or "job"


class InMemoryJobRepository:
    """JobRepository Protocol impl backed by an in-memory list + slug map."""

    def __init__(self, jobs: list[JobPosting]) -> None:
        # Preserve load order for stable slug disambiguation.
        self._records: list[JobRecord] = []
        self._by_id: dict[str, JobRecord] = {}

        seen_counts: dict[str, int] = {}
        for job in jobs:
            base = _slugify(job.title)
            seen_counts[base] = seen_counts.get(base, 0) + 1
            if seen_counts[base] == 1:
                slug = base
            else:
                slug = f"{base}-{seen_counts[base]}"
            record = JobRecord(id=slug, job=job)
            self._records.append(record)
            self._by_id[slug] = record

    # ---- reads ------------------------------------------------------------

    def get(self, job_id: str) -> JobRecord | None:
        return self._by_id.get(job_id)

    def list_filtered(self, keyword: str, skill: str) -> list[JobRecord]:
        """Apply keyword/skill filters and return the full matching list.

        Used by :meth:`list` for pagination and by property-based tests
        to compare paged concatenation against the full filtered set
        (R3.7).
        """
        filtered_jobs = search_jobs(
            [r.job for r in self._records],
            keyword=keyword,
            skill=skill,
        )
        # Map the filtered JobPosting instances back to records. Because
        # search_jobs preserves order and does not mutate, we can use
        # identity-or-position matching — but identity is cleaner and
        # survives any future search_jobs refactor that might emit new
        # objects.
        job_to_record = {id(r.job): r for r in self._records}
        out: list[JobRecord] = []
        for job in filtered_jobs:
            rec = job_to_record.get(id(job))
            if rec is not None:
                out.append(rec)
        return out

    def list(
        self, *, page: int, limit: int, keyword: str, skill: str
    ) -> tuple[list[JobRecord], int]:
        """Paginated list. Returns ``(page_items, total_filtered_count)``."""
        filtered = self.list_filtered(keyword=keyword, skill=skill)
        total = len(filtered)
        start = (page - 1) * limit
        end = start + limit
        return filtered[start:end], total

    # ---- helpers exposed for handlers/tests ------------------------------

    @staticmethod
    def page_count(total: int, limit: int) -> int:
        """Return ``ceil(total / limit)`` for ``total > 0``, else 0."""
        return ceil(total / limit) if total > 0 else 0
