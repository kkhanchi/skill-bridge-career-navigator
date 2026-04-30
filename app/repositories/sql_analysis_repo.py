"""SQLAlchemy implementation of :class:`AnalysisRepository`.

Analyses are write-once from the client's perspective — no PATCH or
DELETE endpoint — so the repository surface is minimal.

Phase 3 note: ``analyses.user_id`` is NOT NULL after migration 0002.
The Phase 1/2 ``create()`` method raises; use ``create_for_user``.
``get_for_user`` enforces anti-enumeration (R12.7): wrong-owner rows
are invisible in the result set.

Requirement reference: R2.1, R2.2, R12.1, R12.2, R12.7.
"""

from __future__ import annotations

from sqlalchemy import select

from app.db.models import AnalysisORM
from app.db.session import get_db_session
from app.repositories._mappers import (
    analysis_record_from_row,
    analysis_row_from_record,
)
from app.repositories.base import AnalysisRecord


class SqlAlchemyAnalysisRepository:
    """Repository Protocol impl for stored gap analyses."""

    # ---- Phase 1/2 methods ---------------------------------------------

    def create(self, record: AnalysisRecord) -> AnalysisRecord:
        raise RuntimeError(
            "SqlAlchemyAnalysisRepository.create() is unavailable after "
            "Phase 3 migration 0002; use create_for_user(user_id, record)"
        )

    def get(self, analysis_id: str) -> AnalysisRecord | None:
        session = get_db_session()
        row = session.get(AnalysisORM, analysis_id)
        return analysis_record_from_row(row) if row is not None else None

    # ---- Phase 3 multi-tenant methods ----------------------------------

    def _create_impl(
        self, user_id: str, record: AnalysisRecord
    ) -> AnalysisRecord:
        """Shared insert path used by ``create_for_user``.

        Centralising the mapper call + ``user_id`` stamp here keeps
        the Phase 1/2 ``create`` safely broken without duplicating
        the real insert logic.
        """
        session = get_db_session()
        row = analysis_row_from_record(record)
        row.user_id = user_id
        session.add(row)
        session.flush()
        return analysis_record_from_row(row)

    def create_for_user(
        self, user_id: str, record: AnalysisRecord
    ) -> AnalysisRecord:
        return self._create_impl(user_id, record)

    def get_for_user(
        self, analysis_id: str, user_id: str
    ) -> AnalysisRecord | None:
        """Fetch only if owned by ``user_id``.

        Anti-enumeration (R12.7): wrong-owner rows are invisible in
        the query, indistinguishable from a missing id.
        """
        session = get_db_session()
        row = session.scalar(
            select(AnalysisORM).where(
                (AnalysisORM.id == analysis_id)
                & (AnalysisORM.user_id == user_id)
            )
        )
        return analysis_record_from_row(row) if row is not None else None
