"""SQLAlchemy implementation of :class:`JobRepository`.

The list endpoint drives `GET /api/v1/jobs` with keyword + skill
filters and pagination. Key design points:

- Deterministic ordering via ``ORDER BY id ASC`` so pagination is
  stable across repeated calls (R8.3).
- The ``keyword`` filter uses SQL ``ILIKE`` against title +
  description — works identically on SQLite and Postgres.
- The ``skill`` filter runs in Python after the SELECT. JSON
  contains operators differ between SQLite and Postgres;
  post-filtering in Python keeps the repository portable until
  the Phase 5 Postgres-specific optimization (R8.5).

Design reference: `.kiro/specs/phase-2-persistence/design.md` §SqlAlchemyJobRepository.list.
Requirement reference: R2.1, R2.2, R8.1, R8.2, R8.3, R8.5.
"""

from __future__ import annotations

from sqlalchemy import or_, select

from app.db.models import JobORM
from app.db.session import get_db_session
from app.repositories._mappers import job_record_from_row
from app.repositories.base import JobRecord


class SqlAlchemyJobRepository:
    """Repository Protocol impl for the job catalog."""

    def get(self, job_id: str) -> JobRecord | None:
        session = get_db_session()
        row = session.get(JobORM, job_id)
        return job_record_from_row(row) if row is not None else None

    def list(
        self,
        *,
        page: int,
        limit: int,
        keyword: str,
        skill: str,
    ) -> tuple[list[JobRecord], int]:
        """Return ``(page_items, total_filtered_count)``.

        Mirrors :class:`InMemoryJobRepository.list` semantics: the
        ``total`` count is the filtered-set size (not page size), and
        out-of-range pages return empty ``items`` with the real
        ``total`` unchanged.
        """
        session = get_db_session()

        stmt = select(JobORM)

        keyword_clean = (keyword or "").strip()
        if keyword_clean:
            pattern = f"%{keyword_clean}%"
            stmt = stmt.where(
                or_(
                    JobORM.title.ilike(pattern),
                    JobORM.description.ilike(pattern),
                )
            )

        # Deterministic ordering so concatenating pages 1..N yields the
        # full filtered list in a stable order (R8.3, R8.4).
        stmt = stmt.order_by(JobORM.id.asc())

        rows = list(session.scalars(stmt).all())

        # Python-side skill filter — portable across SQLite and
        # Postgres. Matches the InMemoryJobRepository contract: a job
        # matches when the skill (case-insensitive) appears in either
        # required_skills or preferred_skills.
        skill_clean = (skill or "").strip().lower()
        if skill_clean:
            rows = [
                r for r in rows
                if skill_clean in {s.lower() for s in (r.required_skills + r.preferred_skills)}
            ]

        total = len(rows)
        start = (page - 1) * limit
        page_rows = rows[start : start + limit]

        return [job_record_from_row(r) for r in page_rows], total
