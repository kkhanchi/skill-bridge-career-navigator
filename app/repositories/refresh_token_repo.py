"""In-memory :class:`RefreshTokenRepository` implementation (Phase 3).

Dict-backed store keyed by ``jti``. ``revoke(jti)`` is idempotent — it
only returns ``True`` when the call transitions a live row to the
revoked state. Calling it on an already-revoked or unknown jti
returns ``False`` without side effects. This matches the contract the
``/auth/logout`` handler relies on to return 204 in all well-formed
cases.

Design reference: `.kiro/specs/phase-3-auth/design.md` §Refresh-token repositories.
Requirement reference: R12.5, R12.6.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from uuid import uuid4

from app.repositories.base import RefreshTokenRecord


class InMemoryRefreshTokenRepository:
    """RefreshTokenRepository Protocol impl using a per-process dict."""

    def __init__(self) -> None:
        # jti is naturally unique per token, so it's the right primary
        # key here — a secondary id->jti mapping would just duplicate
        # it.
        self._by_jti: dict[str, RefreshTokenRecord] = {}
        self._lock = threading.Lock()

    def create(
        self,
        *,
        user_id: str,
        jti: str,
        expires_at: datetime,
    ) -> RefreshTokenRecord:
        record = RefreshTokenRecord(
            id=uuid4().hex,
            user_id=user_id,
            jti=jti,
            expires_at=expires_at,
            revoked_at=None,
            created_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._by_jti[jti] = record
        return record

    def get_by_jti(self, jti: str) -> RefreshTokenRecord | None:
        return self._by_jti.get(jti)

    def revoke(self, jti: str) -> bool:
        """Mark the token revoked. Idempotent.

        Returns True only when the call flipped a live token to
        revoked. Returns False if the jti is unknown or already
        revoked — the handler treats both identically (204).
        """
        with self._lock:
            record = self._by_jti.get(jti)
            if record is None or record.revoked_at is not None:
                return False
            # Dataclasses are mutable; replace the record so callers
            # holding the previous reference see stable data.
            self._by_jti[jti] = RefreshTokenRecord(
                id=record.id,
                user_id=record.user_id,
                jti=record.jti,
                expires_at=record.expires_at,
                revoked_at=datetime.now(timezone.utc),
                created_at=record.created_at,
            )
            return True

    def is_revoked(self, jti: str) -> bool:
        """True iff the jti exists AND ``revoked_at IS NOT NULL``.

        An unknown jti returns False (it is not "revoked"; it simply
        never existed). The ``/auth/refresh`` handler calls
        ``get_by_jti`` first anyway to separate the two states — this
        method is mostly useful inside ``revoke`` for idempotency.
        """
        record = self._by_jti.get(jti)
        return record is not None and record.revoked_at is not None
