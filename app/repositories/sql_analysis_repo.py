"""SQLAlchemy implementation of :class:`AnalysisRepository`.

Analyses are write-once from the client's perspective — no PATCH or
DELETE endpoint — so the repository surface is minimal.

Requirement reference: R2.1, R2.2.
"""

from __future__ import annotations

from app.db.models import AnalysisORM
from app.db.session import get_db_session
from app.repositories._mappers import (
    analysis_record_from_row,
    analysis_row_from_record,
)
from app.repositories.base import AnalysisRecord


class SqlAlchemyAnalysisRepository:
    """Repository Protocol impl for stored gap analyses."""

    def create(self, record: AnalysisRecord) -> AnalysisRecord:
        session = get_db_session()
        row = analysis_row_from_record(record)
        session.add(row)
        session.flush()
        return analysis_record_from_row(row)

    def get(self, analysis_id: str) -> AnalysisRecord | None:
        session = get_db_session()
        row = session.get(AnalysisORM, analysis_id)
        return analysis_record_from_row(row) if row is not None else None
