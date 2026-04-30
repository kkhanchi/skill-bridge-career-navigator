"""Unit tests for ORM <-> Record mapper functions.

These tests are framework-agnostic: they construct ORM rows and
Record dataclasses directly in Python (no Flask, no DB, no Alembic).
That keeps them fast and makes them a good canary for domain-model
drift.

Requirement reference: R2.2, R7.4.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.gap_analyzer import analyze_gap
from app.core.models import (
    CategorizationResult,
    GapResult,
    JobPosting,
    LearningResource,
    Roadmap,
    RoadmapPhase,
    UserProfile,
)
from app.core.roadmap_generator import generate_roadmap
from app.db.models import AnalysisORM, JobORM, ProfileORM, RoadmapORM
from app.repositories._mappers import (
    _build_resource_index,
    analysis_record_from_row,
    analysis_row_from_record,
    job_record_from_row,
    job_row_from_record,
    profile_record_from_row,
    profile_row_from_record,
    roadmap_record_from_row,
    roadmap_row_from_record,
)
from app.repositories.base import (
    AnalysisRecord,
    JobRecord,
    ProfileRecord,
    RoadmapRecord,
)


# ---------------------------------------------------------------------------
# ProfileRecord <-> ProfileORM
# ---------------------------------------------------------------------------


def test_profile_record_round_trip():
    original = ProfileRecord(
        id="p-1",
        profile=UserProfile(
            name="Jane Doe",
            skills=["Python", "SQL"],
            experience_years=3,
            education="Bachelor's",
            target_role="Backend Developer",
        ),
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    row = profile_row_from_record(original)
    restored = profile_record_from_row(row)

    assert restored.id == original.id
    assert restored.profile == original.profile
    assert restored.created_at == original.created_at
    assert restored.updated_at == original.updated_at


def test_profile_mapper_preserves_timezone_awareness():
    now = datetime.now(timezone.utc)
    row = ProfileORM(
        id="p-1", name="X", skills=["Python"], experience_years=1,
        education="", target_role="R",
        created_at=now, updated_at=now,
    )
    record = profile_record_from_row(row)

    assert record.created_at.tzinfo is not None
    assert record.updated_at.tzinfo is not None


# ---------------------------------------------------------------------------
# JobRecord <-> JobORM
# ---------------------------------------------------------------------------


def test_job_record_round_trip():
    original = JobRecord(
        id="backend-developer",
        job=JobPosting(
            title="Backend Developer",
            description="Build APIs",
            required_skills=["Python", "SQL"],
            preferred_skills=["Docker"],
            experience_level="Mid",
        ),
    )

    row = job_row_from_record(original)
    restored = job_record_from_row(row)

    assert restored.id == original.id
    assert restored.job == original.job


# ---------------------------------------------------------------------------
# AnalysisRecord <-> AnalysisORM
# ---------------------------------------------------------------------------


def test_analysis_record_round_trip():
    gap = GapResult(
        matched_required=["Python"],
        matched_preferred=[],
        missing_required=["SQL"],
        missing_preferred=["Docker"],
        match_percentage=50,
    )
    categorization = CategorizationResult(
        groups={"Programming": ["SQL"], "DevOps": ["Docker"]},
        summary="You have one matching skill for this role.",
        is_fallback=True,
    )
    original = AnalysisRecord(
        id="a-1",
        profile_id="p-1",
        job_id="backend-developer",
        gap=gap,
        categorization=categorization,
        created_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
    )

    row = analysis_row_from_record(original)
    # The row's `result` dict is a nested gap + categorization payload;
    # it's what would get stored in the JSON column.
    assert "gap" in row.result
    assert "categorization" in row.result

    restored = analysis_record_from_row(row)

    assert restored.id == original.id
    assert restored.profile_id == original.profile_id
    assert restored.job_id == original.job_id
    assert restored.gap == original.gap
    assert restored.categorization == original.categorization


def test_analysis_mapper_handles_empty_profile_id():
    # ProfileRecord.profile_id is a string; AnalysisORM.profile_id is
    # nullable. Empty string round-trips to None and back.
    row = AnalysisORM(
        id="a-2",
        profile_id=None,
        job_id="job-1",
        result={"gap": {}, "categorization": {}},
    )
    record = analysis_record_from_row(row)

    assert record.profile_id == ""

    back = analysis_row_from_record(record)
    assert back.profile_id is None


# ---------------------------------------------------------------------------
# RoadmapRecord <-> RoadmapORM (the non-trivial one)
# ---------------------------------------------------------------------------


def _sample_resources() -> list[LearningResource]:
    return [
        LearningResource(
            name="REST API Course", skill="REST APIs",
            resource_type="course", estimated_hours=12,
            url="https://example.com/rest",
        ),
        LearningResource(
            name="Docker Essentials", skill="Docker",
            resource_type="course", estimated_hours=12,
            url="https://example.com/docker",
        ),
        LearningResource(
            name="AWS Cloud Practitioner", skill="AWS",
            resource_type="certification", estimated_hours=25,
            url="https://example.com/aws",
        ),
    ]


def test_roadmap_mapper_preserves_phases_and_resources():
    # Build a realistic roadmap via generate_roadmap so every resource
    # carries a uuid id matching the real production path.
    profile = UserProfile(
        name="T", skills=["Python"], experience_years=1,
        education="BSc", target_role="Backend Developer",
    )
    job = JobPosting(
        title="Backend Developer", description="Build APIs",
        required_skills=["Python", "REST APIs", "Git"],
        preferred_skills=["Docker", "AWS"],
        experience_level="Mid",
    )
    gap = analyze_gap(profile, job)
    roadmap = generate_roadmap(gap, _sample_resources())

    original = RoadmapRecord(
        id="r-1",
        analysis_id="a-1",
        roadmap=roadmap,
        resource_index=_build_resource_index(roadmap),
        created_at=datetime(2026, 1, 4, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
    )

    row = roadmap_row_from_record(original)
    restored = roadmap_record_from_row(row)

    # Phase labels preserved.
    assert [p.label for p in restored.roadmap.phases] == [
        p.label for p in original.roadmap.phases
    ]
    # Resources preserved (ids, names, completed flags).
    for orig_phase, new_phase in zip(original.roadmap.phases, restored.roadmap.phases):
        assert len(new_phase.resources) == len(orig_phase.resources)
        for orig_res, new_res in zip(orig_phase.resources, new_phase.resources):
            assert new_res.id == orig_res.id
            assert new_res.name == orig_res.name
            assert new_res.skill == orig_res.skill
            assert new_res.completed == orig_res.completed


def test_roadmap_mapper_rebuilds_resource_index_equivalent_to_generator():
    # The resource_index the mapper rebuilds from the serialized phases
    # MUST match what _build_resource_index produces directly on the
    # roadmap. This is the contract the PATCH handler depends on.
    profile = UserProfile(
        name="T", skills=[], experience_years=0,
        education="", target_role="Backend Developer",
    )
    job = JobPosting(
        title="Backend Developer", description="d",
        required_skills=["Python", "SQL", "REST APIs"],
        preferred_skills=["Docker"],
        experience_level="Mid",
    )
    gap = analyze_gap(profile, job)
    roadmap = generate_roadmap(gap, _sample_resources())

    rec = RoadmapRecord(
        id="r-1", analysis_id="a-1", roadmap=roadmap,
        resource_index=_build_resource_index(roadmap),
    )

    row = roadmap_row_from_record(rec)
    restored = roadmap_record_from_row(row)

    assert restored.resource_index == rec.resource_index
    # Every id in the index resolves to the right (phase, resource) pair.
    for rid, (phase_idx, res_idx) in restored.resource_index.items():
        actual = restored.roadmap.phases[phase_idx].resources[res_idx]
        assert actual.id == rid


def test_build_resource_index_skips_resources_without_ids():
    # Defensive: resources without ids (legacy data) don't crash the
    # mapper; they just don't appear in the index.
    roadmap = Roadmap(phases=[
        RoadmapPhase(label="Phase 1", resources=[
            LearningResource(
                name="Legacy", skill="Python", resource_type="course",
                estimated_hours=5, url="https://example.com",
                completed=False,  # id defaults to ""
            ),
            LearningResource(
                name="Modern", skill="SQL", resource_type="course",
                estimated_hours=5, url="https://example.com",
                completed=False, id="keeps-id",
            ),
        ]),
    ])

    index = _build_resource_index(roadmap)
    assert list(index.keys()) == ["keeps-id"]
    assert index["keeps-id"] == (0, 1)
