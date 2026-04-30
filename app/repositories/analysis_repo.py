"""In-memory :class:`AnalysisRepository`.

Write-once, read-many: analyses are immutable once created (there is no
PATCH endpoint for them). Keyed by ``uuid4().hex`` assigned upstream in
the handler, which stamps the record's ``id`` before calling
:meth:`create`.

Phase 3 additions (ADR-014):
- ``create_for_user`` / ``get_for_user`` scope to owning user.
- Ownership tracked via a sidecar ``_owners`` dict, same pattern as
  :class:`InMemoryProfileRepository`.

Design reference: `.kiro/specs/phase-1-rest-api/design.md` §AnalysisRepository.
Requirement reference: R4.1, R4.4, R4.5, R11.2, R12.1, R12.2, R12.7.
"""

from __future__ import annotations

import threading

from app.repositories.base import AnalysisRecord


class InMemoryAnalysisRepository:
    """AnalysisRepository Protocol impl using a per-process dict."""

    def __init__(self) -> None:
        self._records: dict[str, AnalysisRecord] = {}
        self._owners: dict[str, str] = {}
        self._lock = threading.Lock()

    # ---- Phase 1/2 methods ---------------------------------------------

    def create(self, record: AnalysisRecord) -> AnalysisRecord:
        with self._lock:
            self._records[record.id] = record
        return record

    def get(self, analysis_id: str) -> AnalysisRecord | None:
        return self._records.get(analysis_id)

    # ---- Phase 3 multi-tenant methods ----------------------------------

    def create_for_user(
        self, user_id: str, record: AnalysisRecord
    ) -> AnalysisRecord:
        stored = self.create(record)
        with self._lock:
            self._owners[stored.id] = user_id
        return stored

    def get_for_user(
        self, analysis_id: str, user_id: str
    ) -> AnalysisRecord | None:
        # Anti-enumeration: wrong-owner collapses to the same "not found"
        # surface as unknown id.
        if self._owners.get(analysis_id) != user_id:
            return None
        return self._records.get(analysis_id)
