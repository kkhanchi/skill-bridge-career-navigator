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

from app.core.models import UserProfile
from app.db.models import ProfileORM
from app.db.session import get_db_session
from app.repositories._mappers import profile_record_from_row
from app.repositories.base import ProfileRecord


class SqlAlchemyProfileRepository:
    """Repository Protocol impl backed by SQLAlchemy + the request session."""

    def create(self, profile: UserProfile) -> ProfileRecord:
        session = get_db_session()
        now = datetime.now(timezone.utc)
        row = ProfileORM(
            id=uuid4().hex,
            user_id=None,  # Phase 3 wires auth
            name=profile.name,
            skills=list(profile.skills),
            experience_years=profile.experience_years,
            education=profile.education,
            target_role=profile.target_role,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        # Flush now so the generated row (including any server-side
        # defaults) is observable to the caller — commit happens in
        # teardown_request.
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
