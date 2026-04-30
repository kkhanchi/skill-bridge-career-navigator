"""In-memory :class:`ProfileRepository` implementation.

Dict-backed store keyed by ``uuid4().hex``, guarded by a ``threading.Lock``
so concurrent requests within a single process don't race. Multi-worker
consistency is an explicit Phase 1 non-goal (gunicorn should run with
``-w 1`` for now; Phase 2 introduces a shared database).

Phase 3 additions (ADR-014):
- ``*_for_user`` methods scope lookups and mutations to rows owned by
  a specific user. Ownership is tracked via a sidecar ``_owners`` dict
  rather than adding a ``user_id`` field to :class:`ProfileRecord` —
  that keeps the Phase 1/2 Record construction sites unchanged.
- Anti-enumeration (R12.7): ``get_for_user`` returns ``None`` for both
  "id doesn't exist" and "id exists but owned by someone else", so the
  caller can't probe for ids that exist on the tenancy boundary.

Design reference: `.kiro/specs/phase-1-rest-api/design.md` §Repositories.
Requirement reference: R1.1, R1.5, R1.6, R1.7, R11.2, R12.1, R12.2,
R12.3, R12.4, R12.7.
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
        # Ownership sidecar: profile_id -> user_id. Populated by
        # ``create_for_user`` and cleared by ``delete_for_user``.
        # Kept alongside rather than inside ProfileRecord so Phase 1/2
        # callers that never touch the user methods stay compatible
        # with the existing Record shape.
        self._owners: dict[str, str] = {}
        self._lock = threading.Lock()

    # ---- Phase 1/2 methods (unscoped) ----------------------------------

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

    # ---- Phase 3 multi-tenant methods ----------------------------------

    def create_for_user(
        self, user_id: str, profile: UserProfile
    ) -> ProfileRecord:
        """Create a profile owned by ``user_id``."""
        record = self.create(profile)
        with self._lock:
            self._owners[record.id] = user_id
        return record

    def get_for_user(
        self, profile_id: str, user_id: str
    ) -> ProfileRecord | None:
        # Anti-enumeration: unknown id and wrong-owner are
        # indistinguishable from the caller's point of view.
        if self._owners.get(profile_id) != user_id:
            return None
        return self._records.get(profile_id)

    def update_for_user(
        self, profile_id: str, user_id: str, profile: UserProfile
    ) -> ProfileRecord | None:
        if self._owners.get(profile_id) != user_id:
            return None
        return self.update(profile_id, profile)

    def delete_for_user(self, profile_id: str, user_id: str) -> bool:
        if self._owners.get(profile_id) != user_id:
            return False
        with self._lock:
            # Keep the sidecar in sync so a recycled id (unlikely under
            # uuid4 but possible in principle) can't carry stale
            # ownership into a fresh profile.
            self._owners.pop(profile_id, None)
        return self.delete(profile_id)
