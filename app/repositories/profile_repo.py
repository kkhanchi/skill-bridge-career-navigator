"""In-memory :class:`ProfileRepository` implementation.

Dict-backed store keyed by ``uuid4().hex``, guarded by a ``threading.Lock``
so concurrent requests within a single process don't race. Multi-worker
consistency is an explicit Phase 1 non-goal (gunicorn should run with
``-w 1`` for now; Phase 2 introduces a shared database).

Design reference: `.kiro/specs/phase-1-rest-api/design.md` §Repositories.
Requirement reference: R1.1, R1.5, R1.6, R1.7, R11.2.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from uuid import uuid4

from app.core.models import UserProfile
from app.repositories.base import ProfileRecord


class InMemoryProfileRepository:
    """ProfileRepository Protocol impl using a per-process dict."""

    def __init__(self) -> None:
        self._records: dict[str, ProfileRecord] = {}
        self._lock = threading.Lock()

    def create(self, profile: UserProfile) -> ProfileRecord:
        now = datetime.now(timezone.utc)
        record = ProfileRecord(
            id=uuid4().hex,
            profile=profile,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._records[record.id] = record
        return record

    def get(self, profile_id: str) -> ProfileRecord | None:
        # Dict reads are atomic under the GIL; no lock needed.
        return self._records.get(profile_id)

    def update(self, profile_id: str, profile: UserProfile) -> ProfileRecord | None:
        with self._lock:
            existing = self._records.get(profile_id)
            if existing is None:
                return None
            updated = ProfileRecord(
                id=existing.id,
                profile=profile,
                created_at=existing.created_at,
                updated_at=datetime.now(timezone.utc),
            )
            self._records[profile_id] = updated
            return updated

    def delete(self, profile_id: str) -> bool:
        """Remove a profile. Returns True on hit, False if not present."""
        with self._lock:
            return self._records.pop(profile_id, None) is not None
