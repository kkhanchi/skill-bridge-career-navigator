"""SQLAlchemy implementation of :class:`ProfileRepository`.

Conforms structurally to the Phase 1 Protocol in
:mod:`app.repositories.base`; the handler layer never knows which
backend it's talking to. The constructor is argument-free; each
method reaches for ``get_db_session()`` so the class is cheap to
instantiate once per app, not per request.

Design reference: `.kiro/specs/phase-2-persistence/design.md` §SQL Repositories.
Requirement reference: R2.1, R2.2, R2.3, R2.5.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from app.core.models import UserProfile
from app.db.models import ProfileORM
from app.db.session import get_db_session
from app.repositories._mappers import profile_record_from_row
from app.repositories.base import ProfileRecord


class SqlAlchemyProfileRepository:
    """Repository Protocol impl backed by SQLAlchemy + the request session.

    Phase 3 note: ``profiles.user_id`` is NOT NULL after migration 0002.
    The Phase 1/2 ``create()`` method cannot satisfy the FK anymore —
    it raises ``RuntimeError`` to direct callers to ``create_for_user``.
    The in-memory backend still accepts it to keep Phase 1 unit tests
    passing without a Flask app context.
    """

    def create(self, profile: UserProfile) -> ProfileRecord:
        # Migration 0002 made profiles.user_id NOT NULL. Any caller
        # reaching for the unscoped create() on the SQL backend is
        # using the pre-Phase-3 contract — fail loudly rather than
        # silently producing an IntegrityError from the DB layer.
        raise RuntimeError(
            "SqlAlchemyProfileRepository.create() is unavailable after "
            "Phase 3 migration 0002; use create_for_user(user_id, profile)"
        )

    def _create_impl(
        self, user_id: str, profile: UserProfile
    ) -> ProfileRecord:
        """Shared implementation used by ``create_for_user`` (Stage H).

        Kept as a private method so the Phase 1/2 ``create`` signature
        can raise while the real insert lives in one place.
        """
        session = get_db_session()
        now = datetime.now(timezone.utc)
        row = ProfileORM(
            id=uuid4().hex,
            user_id=user_id,
            name=profile.name,
            skills=list(profile.skills),
            experience_years=profile.experience_years,
            education=profile.education,
            target_role=profile.target_role,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.flush()
        return profile_record_from_row(row)

    def get(self, profile_id: str) -> ProfileRecord | None:
        session = get_db_session()
        row = session.get(ProfileORM, profile_id)
        return profile_record_from_row(row) if row is not None else None

    def update(self, profile_id: str, profile: UserProfile) -> ProfileRecord | None:
        session = get_db_session()
        row = session.get(ProfileORM, profile_id)
        if row is None:
            return None
        row.name = profile.name
        row.skills = list(profile.skills)
        row.experience_years = profile.experience_years
        row.education = profile.education
        row.target_role = profile.target_role
        # updated_at is auto-refreshed by `onupdate=func.now()`, but we
        # set it explicitly so the returned record carries the new
        # timestamp without needing a re-read.
        row.updated_at = datetime.now(timezone.utc)
        session.flush()
        return profile_record_from_row(row)

    def delete(self, profile_id: str) -> bool:
        session = get_db_session()
        row = session.get(ProfileORM, profile_id)
        if row is None:
            return False
        session.delete(row)
        session.flush()
        return True

    # ---- Phase 3 multi-tenant methods ----------------------------------

    def create_for_user(
        self, user_id: str, profile: UserProfile
    ) -> ProfileRecord:
        """Create a profile stamped with ``user_id`` (Phase 3 replacement for create)."""
        return self._create_impl(user_id, profile)

    def get_for_user(
        self, profile_id: str, user_id: str
    ) -> ProfileRecord | None:
        """Fetch only if owned by ``user_id``.

        Anti-enumeration (R12.7): rows owned by another user never
        appear in the result set, so the caller cannot distinguish
        "wrong owner" from "doesn't exist".
        """
        session = get_db_session()
        row = session.scalar(
            select(ProfileORM).where(
                (ProfileORM.id == profile_id) & (ProfileORM.user_id == user_id)
            )
        )
        return profile_record_from_row(row) if row is not None else None

    def update_for_user(
        self, profile_id: str, user_id: str, profile: UserProfile
    ) -> ProfileRecord | None:
        session = get_db_session()
        row = session.scalar(
            select(ProfileORM).where(
                (ProfileORM.id == profile_id) & (ProfileORM.user_id == user_id)
            )
        )
        if row is None:
            return None
        row.name = profile.name
        row.skills = list(profile.skills)
        row.experience_years = profile.experience_years
        row.education = profile.education
        row.target_role = profile.target_role
        row.updated_at = datetime.now(timezone.utc)
        session.flush()
        return profile_record_from_row(row)

    def delete_for_user(self, profile_id: str, user_id: str) -> bool:
        session = get_db_session()
        row = session.scalar(
            select(ProfileORM).where(
                (ProfileORM.id == profile_id) & (ProfileORM.user_id == user_id)
            )
        )
        if row is None:
            return False
        session.delete(row)
        session.flush()
        return True
