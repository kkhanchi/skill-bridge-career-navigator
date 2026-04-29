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
# Protocol definitions
# ---------------------------------------------------------------------------


class ProfileRepository(Protocol):
    """Persistence for :class:`UserProfile` records."""

    def create(self, profile: UserProfile) -> ProfileRecord: ...
    def get(self, profile_id: str) -> ProfileRecord | None: ...
    def update(self, profile_id: str, profile: UserProfile) -> ProfileRecord | None: ...
    def delete(self, profile_id: str) -> bool: ...


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
