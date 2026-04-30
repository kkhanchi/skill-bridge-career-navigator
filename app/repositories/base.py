"""Repository contracts: Protocols + Record dataclasses.

A ``Protocol`` per aggregate root describes the repository interface
blueprints depend on. Phase 1 implementations are in-memory dicts; the
Phase 2 swap replaces each with a SQLAlchemy-backed implementation
conforming to the same Protocol — no handler changes required.

Record types are lightweight wrappers that attach identity and
timestamps to the existing core dataclasses without polluting them.
This keeps ``app.core.models`` framework-agnostic.

Design reference: `.kiro/specs/phase-1-rest-api/design.md` §Repositories.
Requirement reference: R11.1, R11.2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from app.core.models import (
    CategorizationResult,
    GapResult,
    JobPosting,
    Roadmap,
    UserProfile,
)


# ---------------------------------------------------------------------------
# Record wrappers
# ---------------------------------------------------------------------------


@dataclass
class ProfileRecord:
    """A stored profile: domain object + identity + audit timestamps."""

    id: str
    profile: UserProfile
    created_at: datetime
    updated_at: datetime


@dataclass
class JobRecord:
    """A job posting wrapped with a stable slug identifier."""

    id: str
    job: JobPosting


@dataclass
class AnalysisRecord:
    """A stored gap analysis, pairing profile/job context with results."""

    id: str
    profile_id: str
    job_id: str
    gap: GapResult
    categorization: CategorizationResult
    created_at: datetime


@dataclass
class RoadmapRecord:
    """A stored roadmap plus an O(1) lookup from resource id to position.

    ``resource_index`` maps ``resource_id`` → ``(phase_index, resource_index)``
    so ``PATCH /roadmaps/{id}/resources/{rid}`` can flip the ``completed``
    flag without scanning the roadmap.
    """

    id: str
    analysis_id: str
    roadmap: Roadmap
    resource_index: dict[str, tuple[int, int]] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Phase 3 Record wrappers
# ---------------------------------------------------------------------------


@dataclass
class UserRecord:
    """A stored user account.

    ``password_hash`` is the argon2id encoded string — never the raw
    password, never hex, never anything but the exact output of
    ``Argon2Hasher.hash``.
    """

    id: str
    email: str
    password_hash: str
    created_at: datetime


@dataclass
class RefreshTokenRecord:
    """A single issued refresh token's bookkeeping row.

    One row per token grant. ``revoked_at`` is None for live tokens and
    a wall-clock timestamp for revoked ones. The token string itself is
    never stored — only its ``jti``.
    """

    id: str
    user_id: str
    jti: str
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Protocol definitions
# ---------------------------------------------------------------------------


class ProfileRepository(Protocol):
    """Persistence for :class:`UserProfile` records."""

    def create(self, profile: UserProfile) -> ProfileRecord: ...
    def get(self, profile_id: str) -> ProfileRecord | None: ...
    def update(self, profile_id: str, profile: UserProfile) -> ProfileRecord | None: ...
    def delete(self, profile_id: str) -> bool: ...

    # ---- Phase 3 multi-tenant variants (ADR-014) ----
    # These parallel the methods above but take ``user_id`` and scope
    # the lookup/mutation to rows owned by that user. Phase 1 tests
    # continue to use the unscoped variants; Phase 3 handlers call
    # only the ``_for_user`` variants.
    def create_for_user(
        self, user_id: str, profile: UserProfile
    ) -> ProfileRecord: ...
    def get_for_user(
        self, profile_id: str, user_id: str
    ) -> ProfileRecord | None: ...
    def update_for_user(
        self, profile_id: str, user_id: str, profile: UserProfile
    ) -> ProfileRecord | None: ...
    def delete_for_user(self, profile_id: str, user_id: str) -> bool: ...


class JobRepository(Protocol):
    """Read-only access to the loaded job catalog, with pagination."""

    def get(self, job_id: str) -> JobRecord | None: ...
    def list(
        self, *, page: int, limit: int, keyword: str, skill: str
    ) -> tuple[list[JobRecord], int]:
        """Return ``(page_items, total_filtered_count)``."""
        ...


class AnalysisRepository(Protocol):
    """Persistence for stored gap analyses."""

    def create(self, record: AnalysisRecord) -> AnalysisRecord: ...
    def get(self, analysis_id: str) -> AnalysisRecord | None: ...

    # ---- Phase 3 multi-tenant variants ----
    def create_for_user(
        self, user_id: str, record: AnalysisRecord
    ) -> AnalysisRecord: ...
    def get_for_user(
        self, analysis_id: str, user_id: str
    ) -> AnalysisRecord | None: ...


class RoadmapRepository(Protocol):
    """Persistence for roadmaps and per-resource completion updates."""

    def create(self, record: RoadmapRecord) -> RoadmapRecord: ...
    def get(self, roadmap_id: str) -> RoadmapRecord | None: ...
    def update_resource(
        self, roadmap_id: str, resource_id: str, completed: bool
    ) -> RoadmapRecord | None:
        """Flip ``completed`` on a specific resource.

        Returns:
            Updated :class:`RoadmapRecord` on success, or ``None`` when
            either the roadmap or the specific resource does not exist
            (handler inspects ``get()`` to distinguish the two 404 codes).
        """
        ...

    # ---- Phase 3 multi-tenant variants ----
    def create_for_user(
        self, user_id: str, record: RoadmapRecord
    ) -> RoadmapRecord: ...
    def get_for_user(
        self, roadmap_id: str, user_id: str
    ) -> RoadmapRecord | None: ...
    def update_resource_for_user(
        self,
        roadmap_id: str,
        resource_id: str,
        user_id: str,
        completed: bool,
    ) -> RoadmapRecord | None: ...


# ---------------------------------------------------------------------------
# Phase 3 Protocols
# ---------------------------------------------------------------------------


class UserRepository(Protocol):
    """Persistence for :class:`UserRecord` accounts.

    Email normalization (strip + lower-case) is the repository's job,
    not the handler's. Callers pass raw email strings; the repository
    is responsible for consistent casing so ``get_by_email`` and
    ``exists_by_email`` never miss a hit because of a casing quirk.
    """

    def create(self, *, email: str, password_hash: str) -> UserRecord: ...
    def get_by_id(self, user_id: str) -> UserRecord | None: ...
    def get_by_email(self, email: str) -> UserRecord | None: ...
    def exists_by_email(self, email: str) -> bool: ...


class RefreshTokenRepository(Protocol):
    """Persistence for refresh-token grants."""

    def create(
        self, *, user_id: str, jti: str, expires_at: datetime
    ) -> RefreshTokenRecord: ...
    def get_by_jti(self, jti: str) -> RefreshTokenRecord | None: ...
    def revoke(self, jti: str) -> bool:
        """Mark the token revoked.

        Returns True if the row existed and transitioned from live to
        revoked in this call; False if the row didn't exist or was
        already revoked (idempotent). Handlers treat both False cases
        identically — as 401 TOKEN_INVALID.
        """
        ...

    def is_revoked(self, jti: str) -> bool:
        """Return True iff a row for ``jti`` exists AND ``revoked_at IS NOT NULL``.

        An unknown jti returns False — the handler's first step is
        ``get_by_jti`` which separates unknown from known-but-revoked.
        ``is_revoked`` is a convenience for the "already revoked?"
        idempotency check inside ``revoke``.
        """
        ...
