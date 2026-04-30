"""SQLAlchemy implementation of :class:`RefreshTokenRepository`.

Mirrors :mod:`app.repositories.refresh_token_repo` semantically and
delegates storage to :class:`app.db.models.RefreshTokenORM`. Every
method pulls the active request-scoped session via ``get_db_session()``.

Design reference: `.kiro/specs/phase-3-auth/design.md` §Refresh-token repositories.
Requirement reference: R12.5, R12.6.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from app.db.models import RefreshTokenORM
from app.db.session import get_db_session
from app.repositories._mappers import refresh_token_record_from_row
from app.repositories.base import RefreshTokenRecord


class SqlAlchemyRefreshTokenRepository:
    """RefreshTokenRepository Protocol impl backed by SQLAlchemy."""

    def create(
        self,
        *,
        user_id: str,
        jti: str,
        expires_at: datetime,
    ) -> RefreshTokenRecord:
        session = get_db_session()
        row = RefreshTokenORM(
            id=uuid4().hex,
            user_id=user_id,
            jti=jti,
            expires_at=expires_at,
            revoked_at=None,
            created_at=datetime.now(timezone.utc),
        )
        session.add(row)
        session.flush()
        return refresh_token_record_from_row(row)

    def get_by_jti(self, jti: str) -> RefreshTokenRecord | None:
        session = get_db_session()
        row = session.scalar(
            select(RefreshTokenORM).where(RefreshTokenORM.jti == jti)
        )
        return refresh_token_record_from_row(row) if row is not None else None

    def revoke(self, jti: str) -> bool:
        """Idempotent revoke.

        Returns True only when the row transitioned from live
        (``revoked_at IS NULL``) to revoked. Unknown jti or
        already-revoked row both return False without changing state.
        """
        session = get_db_session()
        row = session.scalar(
            select(RefreshTokenORM).where(RefreshTokenORM.jti == jti)
        )
        if row is None or row.revoked_at is not None:
            return False
        row.revoked_at = datetime.now(timezone.utc)
        session.flush()
        return True

    def is_revoked(self, jti: str) -> bool:
        session = get_db_session()
        row = session.scalar(
            select(RefreshTokenORM).where(RefreshTokenORM.jti == jti)
        )
        return row is not None and row.revoked_at is not None
