"""In-memory :class:`UserRepository` implementation (Phase 3).

Dict-backed store keyed by ``uuid4().hex`` with a secondary index on
normalized email for O(1) login lookups. Same threading model as the
other in-memory repos: ``threading.Lock`` on writes, lock-free dict
reads under the GIL on single-process deployments.

Email normalization (``strip().lower()``) is the repository's
responsibility — the register/login handlers pass raw user input and
rely on this class to make "``Jane@Co.com``" and "``jane@co.com``"
the same record. Keeping it here (not in the handler) means the
in-memory and SQL backends behave identically without the handler
having to care.

Design reference: `.kiro/specs/phase-3-auth/design.md` §User repositories.
Requirement reference: R12.5, R12.6.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from uuid import uuid4

from app.repositories.base import UserRecord


def _normalize_email(email: str) -> str:
    """Canonicalize: trim surrounding whitespace, fold case.

    Per RFC 5321 the local-part is technically case-sensitive, but
    virtually every provider treats it as insensitive. Lower-casing
    matches user expectation and keeps the uniqueness check usable.
    """
    return email.strip().lower()


class InMemoryUserRepository:
    """UserRepository Protocol impl using a per-process dict."""

    def __init__(self) -> None:
        self._by_id: dict[str, UserRecord] = {}
        # Secondary index: normalized email -> user id. Keeps
        # ``get_by_email`` and ``exists_by_email`` O(1) without
        # scanning ``_by_id.values()``.
        self._by_email: dict[str, str] = {}
        self._lock = threading.Lock()

    def create(self, *, email: str, password_hash: str) -> UserRecord:
        """Insert a new user. Assumes ``exists_by_email`` was False.

        The handler is responsible for the duplicate check — this
        method assumes it's safe to insert. If two concurrent callers
        race past the handler check, the second ``create`` will still
        succeed here (the dict insert overwrites the email-index
        entry), which is a pathological case for the in-memory
        backend. Phase 3 production always runs on the SQL backend
        where the UNIQUE constraint on ``users.email`` is the real
        enforcer.
        """
        normalized = _normalize_email(email)
        record = UserRecord(
            id=uuid4().hex,
            email=normalized,
            password_hash=password_hash,
            created_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._by_id[record.id] = record
            self._by_email[normalized] = record.id
        return record

    def get_by_id(self, user_id: str) -> UserRecord | None:
        return self._by_id.get(user_id)

    def get_by_email(self, email: str) -> UserRecord | None:
        user_id = self._by_email.get(_normalize_email(email))
        if user_id is None:
            return None
        return self._by_id.get(user_id)

    def exists_by_email(self, email: str) -> bool:
        return _normalize_email(email) in self._by_email
