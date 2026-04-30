"""SQLAlchemy 2.x ORM models for Phase 2.

Five tables covering the full Phase 2 schema:

- :class:`UserORM` — created now, consumed by Phase 3 auth.
- :class:`ProfileORM` — candidate career profile; `user_id` is
  nullable until Phase 3 flips it NOT NULL.
- :class:`JobORM` — job catalog with slug primary key matching the
  Phase 1 `InMemoryJobRepository` id contract (ADR-005).
- :class:`AnalysisORM` — stored gap analysis result + categorization.
- :class:`RoadmapORM` — phased learning roadmap derived from an
  analysis.

JSON-bearing columns use the portable ``_JSONB`` variant type so the
same model definitions work against SQLite (JSON text) and Postgres
(native JSONB).

Design reference: `.kiro/specs/phase-2-persistence/design.md` §Data Models.
Requirement reference: R1.1, R1.3, R1.4, R1.5, R1.7.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# Portable JSON type: plain JSON on SQLite, native JSONB on Postgres.
# Same column definition works against both — no dialect branching at
# the model level (ADR-010).
_JSONB = JSON().with_variant(JSONB(), "postgresql")


class UserORM(Base):
    """Account record. Phase 2 creates the table; Phase 3 wires auth.

    ``email`` carries a UNIQUE constraint so Phase 3 login lookups get
    an index for free.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    email: Mapped[str] = mapped_column(
        String(320), unique=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class ProfileORM(Base):
    """User's career profile.

    ``user_id`` stays nullable in Phase 2 — Phase 3 flips it to NOT NULL
    after backfilling existing rows. ``skills`` is a JSON list of
    strings; per-skill validation happens at the Pydantic layer.
    """

    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    skills: Mapped[list[str]] = mapped_column(_JSONB, nullable=False)
    experience_years: Mapped[int] = mapped_column(Integer, nullable=False)
    education: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    target_role: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class JobORM(Base):
    """Job posting with slug primary key (ADR-005).

    Slugs are derived from the title by ``InMemoryJobRepository`` and
    reused by the seed script — Phase 1 and Phase 2 produce identical
    ids for the same ``jobs.json`` input (R5.4).
    """

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    required_skills: Mapped[list[str]] = mapped_column(_JSONB, nullable=False)
    preferred_skills: Mapped[list[str]] = mapped_column(_JSONB, nullable=False)
    experience_level: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )


class AnalysisORM(Base):
    """Stored gap analysis.

    The ``result`` JSON carries both the gap (matched/missing skills +
    percentage) and the categorization (groups + summary + fallback
    flag). Phase 2 handlers serialize/deserialize this through the
    mapper module so the Pydantic response shape stays fixed.

    Cascade behavior (design §Open Question 4):
    - ``profile_id`` ON DELETE SET NULL: analyses survive profile
      deletion but lose the link.
    - ``job_id`` ON DELETE RESTRICT: you can't delete a job that an
      analysis still references.
    """

    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    profile_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey("profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    job_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("jobs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    result: Mapped[dict[str, Any]] = mapped_column(_JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class RoadmapORM(Base):
    """Phased learning roadmap generated from an analysis.

    ``phases`` is a JSON list of ``{label, resources}`` dicts where
    every resource carries a uuid id (assigned by ``generate_roadmap``).
    ``PATCH /api/v1/roadmaps/{id}/resources/{rid}`` mutates a single
    resource's ``completed`` flag in place — the repository must call
    ``flag_modified(row, "phases")`` afterwards so SQLAlchemy detects
    the change (R7.1).

    ``analysis_id`` uses ON DELETE CASCADE: a roadmap is strictly
    derived from its analysis and has no meaning without it.
    """

    __tablename__ = "roadmaps"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    phases: Mapped[list[dict[str, Any]]] = mapped_column(_JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class RefreshTokenORM(Base):
    """A single refresh-token grant (Phase 3).

    One row per issued refresh token. We never store the token string
    itself — only its ``jti`` (the JWT's unique id claim). Verifying a
    refresh request:

    1. Decode the presented JWT -> extract jti.
    2. Look the row up by jti.
    3. Row exists, not expired, ``revoked_at IS NULL`` -> accept.

    Rotation-on-refresh sets ``revoked_at = now()`` on the old row and
    inserts a new row for the replacement token. Reuse of a revoked
    jti is treated identically to an unknown jti — both return 401
    TOKEN_INVALID. (See design §Open Question Q3 on theft detection.)

    ``user_id`` uses ON DELETE CASCADE: deleting a user wipes their
    token grants.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # jti is the claim we look up by; unique so a forged duplicate
    # cannot collide with an existing row.
    jti: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    # Null until the token is revoked. A NOT NULL value timestamps the
    # revocation for audit / future theft-detection windows.
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
