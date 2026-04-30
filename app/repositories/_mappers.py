"""ORM row <-> Record translation.

The SQLAlchemy repositories in :mod:`app.repositories.sql_*_repo` work
in terms of ORM rows (``ProfileORM``, ``JobORM``, …); the handler
layer works in terms of the Phase 1 ``*Record`` dataclasses. This
module is the thin translation layer between them.

Keeping it separate from the repository files has two wins:

1. The mapping functions are pure — no DB access, no Flask context —
   so they're cheap to unit-test in isolation.
2. The :class:`RoadmapRecord` side has non-trivial reconstruction
   work (rebuilding ``resource_index`` from the serialized phases
   JSON); isolating that into a named function keeps the repo
   methods focused on query shape.

Requirement reference: R2.2, R7.4.
"""

from __future__ import annotations

from dataclasses import asdict

from app.core.models import (
    CategorizationResult,
    GapResult,
    JobPosting,
    LearningResource,
    Roadmap,
    RoadmapPhase,
    UserProfile,
)
from app.db.models import (
    AnalysisORM,
    JobORM,
    ProfileORM,
    RefreshTokenORM,
    RoadmapORM,
    UserORM,
)
from app.repositories.base import (
    AnalysisRecord,
    JobRecord,
    ProfileRecord,
    RefreshTokenRecord,
    RoadmapRecord,
    UserRecord,
)


# ---------------------------------------------------------------------------
# ProfileRecord <-> ProfileORM
# ---------------------------------------------------------------------------


def profile_record_from_row(row: ProfileORM) -> ProfileRecord:
    return ProfileRecord(
        id=row.id,
        profile=UserProfile(
            name=row.name,
            skills=list(row.skills),
            experience_years=row.experience_years,
            education=row.education,
            target_role=row.target_role,
        ),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def profile_row_from_record(rec: ProfileRecord) -> ProfileORM:
    return ProfileORM(
        id=rec.id,
        user_id=None,  # Phase 2: not populated until Phase 3 wires auth
        name=rec.profile.name,
        skills=list(rec.profile.skills),
        experience_years=rec.profile.experience_years,
        education=rec.profile.education,
        target_role=rec.profile.target_role,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
    )


# ---------------------------------------------------------------------------
# JobRecord <-> JobORM
# ---------------------------------------------------------------------------


def job_record_from_row(row: JobORM) -> JobRecord:
    return JobRecord(
        id=row.id,
        job=JobPosting(
            title=row.title,
            description=row.description,
            required_skills=list(row.required_skills),
            preferred_skills=list(row.preferred_skills),
            experience_level=row.experience_level,
        ),
    )


def job_row_from_record(rec: JobRecord) -> JobORM:
    return JobORM(
        id=rec.id,
        title=rec.job.title,
        description=rec.job.description,
        required_skills=list(rec.job.required_skills),
        preferred_skills=list(rec.job.preferred_skills),
        experience_level=rec.job.experience_level,
    )


# ---------------------------------------------------------------------------
# AnalysisRecord <-> AnalysisORM
# ---------------------------------------------------------------------------


def analysis_record_from_row(row: AnalysisORM) -> AnalysisRecord:
    result = row.result or {}
    gap_dict = result.get("gap", {})
    cat_dict = result.get("categorization", {})
    gap = GapResult(
        matched_required=list(gap_dict.get("matched_required", [])),
        matched_preferred=list(gap_dict.get("matched_preferred", [])),
        missing_required=list(gap_dict.get("missing_required", [])),
        missing_preferred=list(gap_dict.get("missing_preferred", [])),
        match_percentage=int(gap_dict.get("match_percentage", 0)),
    )
    categorization = CategorizationResult(
        groups=dict(cat_dict.get("groups", {})),
        summary=str(cat_dict.get("summary", "")),
        is_fallback=bool(cat_dict.get("is_fallback", False)),
    )
    return AnalysisRecord(
        id=row.id,
        profile_id=row.profile_id or "",
        job_id=row.job_id,
        gap=gap,
        categorization=categorization,
        created_at=row.created_at,
    )


def analysis_row_from_record(rec: AnalysisRecord) -> AnalysisORM:
    result = {
        "gap": asdict(rec.gap),
        "categorization": asdict(rec.categorization),
    }
    return AnalysisORM(
        id=rec.id,
        user_id=None,  # Phase 3 wires this
        profile_id=rec.profile_id or None,
        job_id=rec.job_id,
        result=result,
        created_at=rec.created_at,
    )


# ---------------------------------------------------------------------------
# RoadmapRecord <-> RoadmapORM
# ---------------------------------------------------------------------------


def _build_resource_index(roadmap: Roadmap) -> dict[str, tuple[int, int]]:
    """Rebuild a resource_id -> (phase_idx, resource_idx) lookup.

    Matches what :class:`InMemoryRoadmapRepository.create` does via
    :func:`app.core.roadmap_generator.generate_roadmap`. Skips
    resources without an id (shouldn't happen for roadmaps produced
    by the core generator, but the defensive skip keeps this robust
    against legacy data).
    """
    index: dict[str, tuple[int, int]] = {}
    for phase_idx, phase in enumerate(roadmap.phases):
        for resource_idx, resource in enumerate(phase.resources):
            if resource.id:
                index[resource.id] = (phase_idx, resource_idx)
    return index


def _learning_resource_from_dict(data: dict) -> LearningResource:
    return LearningResource(
        name=data["name"],
        skill=data["skill"],
        resource_type=data["resource_type"],
        estimated_hours=int(data["estimated_hours"]),
        url=data["url"],
        completed=bool(data.get("completed", False)),
        id=str(data.get("id", "")),
    )


def roadmap_record_from_row(row: RoadmapORM) -> RoadmapRecord:
    phases = [
        RoadmapPhase(
            label=phase_dict["label"],
            resources=[
                _learning_resource_from_dict(res_dict)
                for res_dict in phase_dict.get("resources", [])
            ],
        )
        for phase_dict in (row.phases or [])
    ]
    roadmap = Roadmap(phases=phases)
    return RoadmapRecord(
        id=row.id,
        analysis_id=row.analysis_id,
        roadmap=roadmap,
        resource_index=_build_resource_index(roadmap),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _learning_resource_to_dict(res: LearningResource) -> dict:
    return {
        "id": res.id,
        "name": res.name,
        "skill": res.skill,
        "resource_type": res.resource_type,
        "estimated_hours": res.estimated_hours,
        "url": res.url,
        "completed": res.completed,
    }


def roadmap_row_from_record(rec: RoadmapRecord) -> RoadmapORM:
    phases_json = [
        {
            "label": phase.label,
            "resources": [
                _learning_resource_to_dict(res) for res in phase.resources
            ],
        }
        for phase in rec.roadmap.phases
    ]
    return RoadmapORM(
        id=rec.id,
        analysis_id=rec.analysis_id,
        phases=phases_json,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
    )


# ---------------------------------------------------------------------------
# UserRecord / RefreshTokenRecord <-> ORM (Phase 3)
# ---------------------------------------------------------------------------


def user_record_from_row(row: UserORM) -> UserRecord:
    """ORM row -> UserRecord (read-only direction).

    The reverse direction (record -> row) is intentionally omitted:
    user rows are only ever created inside the SQL user repository via
    ``session.add(UserORM(...))`` with freshly generated ids, never
    from a pre-existing ``UserRecord``.
    """
    return UserRecord(
        id=row.id,
        email=row.email,
        password_hash=row.password_hash,
        created_at=row.created_at,
    )


def refresh_token_record_from_row(row: RefreshTokenORM) -> RefreshTokenRecord:
    """ORM row -> RefreshTokenRecord."""
    return RefreshTokenRecord(
        id=row.id,
        user_id=row.user_id,
        jti=row.jti,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        created_at=row.created_at,
    )
