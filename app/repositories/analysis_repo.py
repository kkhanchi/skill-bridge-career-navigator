"""In-memory :class:`AnalysisRepository`.

Write-once, read-many: analyses are immutable once created (there is no
PATCH endpoint for them). Keyed by ``uuid4().hex`` assigned upstream in
the handler, which stamps the record's ``id`` before calling
:meth:`create`.

Design reference: `.kiro/specs/phase-1-rest-api/design.md` §AnalysisRepository.
Requirement reference: R4.1, R4.4, R4.5, R11.2.
"""

from __future__ import annotations

import threading

from app.repositories.base import AnalysisRecord


class InMemoryAnalysisRepository:
    """AnalysisRepository Protocol impl using a per-process dict."""

    def __init__(self) -> None:
        self._records: dict[str, AnalysisRecord] = {}
        self._lock = threading.Lock()

    def create(self, record: AnalysisRecord) -> AnalysisRecord:
        with self._lock:
            self._records[record.id] = record
        return record

    def get(self, analysis_id: str) -> AnalysisRecord | None:
        return self._records.get(analysis_id)
