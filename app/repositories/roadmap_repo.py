"""In-memory :class:`RoadmapRepository`.

The interesting method is :meth:`update_resource`: it uses the record's
``resource_index`` (built at roadmap creation time from the uuid4 ids
assigned by ``generate_roadmap``) to locate the target resource in O(1),
flip the ``completed`` flag, and refresh ``updated_at`` — all under a
lock so concurrent PATCHes on sibling resources don't interleave.

``update_resource`` returns ``None`` when the resource is missing, which
the handler uses to emit ``RESOURCE_NOT_FOUND`` (R5.5). When the roadmap
itself is missing, the handler first calls :meth:`get` to distinguish
the two 404 cases (R5.4 vs R5.5).

Phase 3 additions (ADR-014):
- ``*_for_user`` variants scope by user. Ownership via sidecar
  ``_owners`` dict (same pattern as the profile and analysis repos).

Design reference: `.kiro/specs/phase-1-rest-api/design.md` §RoadmapRepository.
Requirement reference: R5.1, R5.3, R5.4, R5.5, R11.2, R12.1, R12.3,
R12.7.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from app.repositories.base import RoadmapRecord


class InMemoryRoadmapRepository:
    """RoadmapRepository Protocol impl."""

    def __init__(self) -> None:
        self._records: dict[str, RoadmapRecord] = {}
        self._owners: dict[str, str] = {}
        self._lock = threading.Lock()

    # ---- Phase 1/2 methods ---------------------------------------------

    def create(self, record: RoadmapRecord) -> RoadmapRecord:
        with self._lock:
            self._records[record.id] = record
        return record

    def get(self, roadmap_id: str) -> RoadmapRecord | None:
        return self._records.get(roadmap_id)

    def update_resource(
        self, roadmap_id: str, resource_id: str, completed: bool
    ) -> RoadmapRecord | None:
        with self._lock:
            record = self._records.get(roadmap_id)
            if record is None:
                return None
            position = record.resource_index.get(resource_id)
            if position is None:
                # Roadmap exists but the specific resource does not. The
                # handler checks ``get()`` afterwards to distinguish this
                # from a missing roadmap for the 404 code path.
                return None

            phase_idx, resource_idx = position
            resource = record.roadmap.phases[phase_idx].resources[resource_idx]
            resource.completed = completed
            record.updated_at = datetime.now(timezone.utc)
            return record

    # ---- Phase 3 multi-tenant methods ----------------------------------

    def create_for_user(
        self, user_id: str, record: RoadmapRecord
    ) -> RoadmapRecord:
        stored = self.create(record)
        with self._lock:
            self._owners[stored.id] = user_id
        return stored

    def get_for_user(
        self, roadmap_id: str, user_id: str
    ) -> RoadmapRecord | None:
        if self._owners.get(roadmap_id) != user_id:
            return None
        return self._records.get(roadmap_id)

    def update_resource_for_user(
        self,
        roadmap_id: str,
        resource_id: str,
        user_id: str,
        completed: bool,
    ) -> RoadmapRecord | None:
        # Ownership check at the gate — unknown or wrong-owner both
        # return None. The handler then calls ``get_for_user`` to
        # distinguish ROADMAP_NOT_FOUND from RESOURCE_NOT_FOUND.
        if self._owners.get(roadmap_id) != user_id:
            return None
        return self.update_resource(roadmap_id, resource_id, completed)
