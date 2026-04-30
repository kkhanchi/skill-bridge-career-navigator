"""SQLAlchemy implementation of :class:`UserRepository`.

Conforms structurally to :class:`app.repositories.base.UserRepository`.
Every method pulls the active request-scoped session via
``get_db_session()``; commit + teardown are the factory's job.

Email normalization matches :mod:`app.repositories.user_repo` exactly
so the two backends are interchangeable.

Design reference: `.kiro/specs/phase-3-auth/design.md` §User repositories.
Requirement reference: R12.5, R12.6.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import exists, select

from app.db.models import UserORM
from app.db.session import get_db_session
from app.repositories._mappers import user_record_from_row
from app.repositories.base import UserRecord
from app.repositories.user_repo import _normalize_email


class SqlAlchemyUserRepository:
    """UserRepository Protocol impl backed by SQLAlchemy."""

    def create(self, *, email: str, password_hash: str) -> UserRecord:
        """Insert a new user. Caller MUST have checked ``exists_by_email``.

        The DB-level UNIQUE constraint on ``users.email`` is the final
        line of defence — if a race slips past the handler check, the
        ``session.flush()`` call here raises ``IntegrityError`` which
        the teardown rolls back. The handler layer maps that to
        ``EMAIL_TAKEN`` at the 409 boundary.
        """
        session = get_db_session()
        normalized = _normalize_email(email)
        row = UserORM(
            id=uuid4().hex,
            email=normalized,
            password_hash=password_hash,
            created_at=datetime.now(timezone.utc),
        )
        session.add(row)
        session.flush()
        return user_record_from_row(row)

    def get_by_id(self, user_id: str) -> UserRecord | None:
        session = get_db_session()
        row = session.get(UserORM, user_id)
        return user_record_from_row(row) if row is not None else None

    def get_by_email(self, email: str) -> UserRecord | None:
        session = get_db_session()
        normalized = _normalize_email(email)
        row = session.scalar(select(UserORM).where(UserORM.email == normalized))
        return user_record_from_row(row) if row is not None else None

    def exists_by_email(self, email: str) -> bool:
        session = get_db_session()
        normalized = _normalize_email(email)
        # EXISTS (...) is a single round-trip returning a bool — cheaper
        # than selecting a row and checking for None.
        return bool(
            session.scalar(
                select(exists().where(UserORM.email == normalized))
            )
        )
