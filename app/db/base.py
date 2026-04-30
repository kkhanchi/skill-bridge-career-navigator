"""SQLAlchemy DeclarativeBase.

This is the single source of truth for the ORM metadata. Every model
under :mod:`app.db.models` inherits from :class:`Base`, and Alembic's
``env.py`` imports ``Base.metadata`` for autogeneration.

Keeping the base minimal (no mixins, no custom metadata naming) makes
``alembic revision --autogenerate`` output predictable across SQLite
and Postgres. Any future naming convention changes land here so they
apply uniformly.

Design reference: `.kiro/specs/phase-2-persistence/design.md` §db/base.py.
Requirement reference: R1.1.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared metadata for every ORM model in :mod:`app.db.models`."""
