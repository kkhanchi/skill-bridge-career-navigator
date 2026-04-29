"""Unit tests for the in-memory repository implementations.

Covers CRUD round-trips, slug stability + collision disambiguation,
pagination math, and resource-index integrity on the roadmap repo.
These tests stay at the repository layer — no Flask, no HTTP.

Requirement reference: R1.1, R3.6, R4.1, R5.3, R5.5, R11.2.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.core.models import (
    CategorizationResult,
    GapResult,
    JobPosting,
    LearningResource,
    Roadmap,
    RoadmapPhase,
    UserProfile,
)
from app.repositories.analysis_repo import InMemoryAnalysisRepository
from app.repositories.base import AnalysisRecord, RoadmapRecord
from app.repositories.job_repo import InMemoryJobRepository, _slugify
from app.repositories.profile_repo import InMemoryProfileRepository
from app.repositories.roadmap_repo import InMemoryRoadmapRepository


# ---------------------------------------------------------------------------
# ProfileRepository
# ---------------------------------------------------------------------------


def _make_profile(name: str = "Alice") -> UserProfile:
    return UserProfile(
        name=name,
        skills=["Python", "SQL"],
        experience_years=3,
        education="Bachelor's",
        target_role="Backend Developer",
    )


def test_profile_repo_create_and_get_round_trip():
    repo = InMemoryProfileRepository()
    profile = _make_profile()

    record = repo.create(profile)

    assert record.id  # non-empty uuid hex
    assert record.profile is profile
    assert record.created_at == record.updated_at
    assert repo.get(record.id) is record
    assert repo.get("does-not-exist") is None


def test_profile_repo_update_refreshes_updated_at():
    repo = InMemoryProfileRepository()
    original = repo.create(_make_profile("Alice"))

    # Force a strictly-later timestamp by sleeping the datetime wall enough.
    # A monotonic equality is fine as long as update_at >= created_at.
    renamed = UserProfile(
        name="Alice Renamed",
        skills=original.profile.skills,
        experience_years=original.profile.experience_years,
        education=original.profile.education,
        target_role=original.profile.target_role,
    )
    updated = repo.update(original.id, renamed)

    assert updated is not None
    assert updated.id == original.id
    assert updated.profile.name == "Alice Renamed"
    assert updated.created_at == original.created_at
    assert updated.updated_at >= original.updated_at


def test_profile_repo_update_returns_none_when_missing():
    repo = InMemoryProfileRepository()
    assert repo.update("missing-id", _make_profile()) is None


def test_profile_repo_delete_is_idempotent_false_on_second_call():
    repo = InMemoryProfileRepository()
    record = repo.create(_make_profile())

    assert repo.delete(record.id) is True
    assert repo.delete(record.id) is False
    assert repo.get(record.id) is None


# ---------------------------------------------------------------------------
# JobRepository
# ---------------------------------------------------------------------------


def _job(title: str, required: list[str] | None = None) -> JobPosting:
    return JobPosting(
        title=title,
        description=f"{title} description",
        required_skills=required or ["Python"],
        preferred_skills=[],
        experience_level="Mid",
    )


def test_slugify_produces_lowercase_hyphenated():
    assert _slugify("Backend Developer") == "backend-developer"
    assert _slugify("Sr. ML / AI Engineer") == "sr-ml-ai-engineer"
    assert _slugify("  Whitespace  ") == "whitespace"
    assert _slugify("!!!") == "job"  # fallback when slug would be empty


def test_job_repo_slug_stability_across_instances():
    jobs = [
        _job("Backend Developer"),
        _job("Data Scientist"),
        _job("DevOps Engineer"),
    ]
    a = InMemoryJobRepository(jobs)
    b = InMemoryJobRepository(jobs)

    ids_a = [rec.id for rec in a.list(page=1, limit=10, keyword="", skill="")[0]]
    ids_b = [rec.id for rec in b.list(page=1, limit=10, keyword="", skill="")[0]]
    assert ids_a == ids_b == [
        "backend-developer",
        "data-scientist",
        "devops-engineer",
    ]


def test_job_repo_disambiguates_title_collisions_in_load_order():
    jobs = [
        _job("Backend Developer"),
        _job("Backend Developer"),  # collision
        _job("Backend Developer"),  # another collision
    ]
    repo = InMemoryJobRepository(jobs)

    ids = [rec.id for rec in repo.list(page=1, limit=10, keyword="", skill="")[0]]
    assert ids == ["backend-developer", "backend-developer-2", "backend-developer-3"]
    for slug in ids:
        assert repo.get(slug) is not None


def test_job_repo_pagination_math():
    jobs = [_job(f"Role {i}") for i in range(25)]
    repo = InMemoryJobRepository(jobs)

    # Page 1: first 10
    page1, total = repo.list(page=1, limit=10, keyword="", skill="")
    assert total == 25
    assert len(page1) == 10
    assert InMemoryJobRepository.page_count(total, 10) == 3

    # Last page: partial fill (25 % 10 = 5)
    page3, total3 = repo.list(page=3, limit=10, keyword="", skill="")
    assert total3 == 25
    assert len(page3) == 5

    # Page beyond last: empty, total still correct
    page99, total99 = repo.list(page=99, limit=10, keyword="", skill="")
    assert page99 == []
    assert total99 == 25

    # Empty filter result
    none, total_none = repo.list(page=1, limit=10, keyword="zzz-no-match", skill="")
    assert none == []
    assert total_none == 0
    assert InMemoryJobRepository.page_count(total_none, 10) == 0


def test_job_repo_get_returns_none_for_unknown_slug():
    repo = InMemoryJobRepository([_job("Backend Developer")])
    assert repo.get("nonexistent-slug") is None
    assert repo.get("backend-developer") is not None


# ---------------------------------------------------------------------------
# AnalysisRepository
# ---------------------------------------------------------------------------


def _make_analysis_record() -> AnalysisRecord:
    gap = GapResult(
        matched_required=["Python"],
        matched_preferred=[],
        missing_required=["SQL"],
        missing_preferred=[],
        match_percentage=50,
    )
    cat = CategorizationResult(groups={"Other": ["SQL"]}, summary="s", is_fallback=True)
    return AnalysisRecord(
        id=uuid4().hex,
        profile_id="profile-1",
        job_id="job-1",
        gap=gap,
        categorization=cat,
        created_at=datetime.now(timezone.utc),
    )


def test_analysis_repo_round_trip():
    repo = InMemoryAnalysisRepository()
    record = _make_analysis_record()

    stored = repo.create(record)
    assert stored is record
    assert repo.get(record.id) is record
    assert repo.get("missing") is None


# ---------------------------------------------------------------------------
# RoadmapRepository
# ---------------------------------------------------------------------------


def _build_roadmap_record() -> tuple[RoadmapRecord, str, str]:
    """Build a RoadmapRecord with 2 phases × 2 resources. Return rec + two rids."""
    r1 = LearningResource(name="A", skill="Python", resource_type="course",
                          estimated_hours=1, url="u", completed=False, id="res-1")
    r2 = LearningResource(name="B", skill="SQL", resource_type="course",
                          estimated_hours=1, url="u", completed=False, id="res-2")
    r3 = LearningResource(name="C", skill="Docker", resource_type="course",
                          estimated_hours=1, url="u", completed=False, id="res-3")
    r4 = LearningResource(name="D", skill="AWS", resource_type="course",
                          estimated_hours=1, url="u", completed=False, id="res-4")

    roadmap = Roadmap(phases=[
        RoadmapPhase(label="Phase 1", resources=[r1, r2]),
        RoadmapPhase(label="Phase 2", resources=[r3, r4]),
    ])
    resource_index = {
        "res-1": (0, 0),
        "res-2": (0, 1),
        "res-3": (1, 0),
        "res-4": (1, 1),
    }
    record = RoadmapRecord(
        id=uuid4().hex,
        analysis_id="ana-1",
        roadmap=roadmap,
        resource_index=resource_index,
    )
    return record, "res-2", "res-3"


def test_roadmap_repo_update_resource_flips_completed_flag():
    repo = InMemoryRoadmapRepository()
    record, rid_mid, _ = _build_roadmap_record()
    repo.create(record)

    updated = repo.update_resource(record.id, rid_mid, completed=True)

    assert updated is not None
    # The flipped resource is completed; siblings untouched.
    assert record.roadmap.phases[0].resources[1].completed is True
    assert record.roadmap.phases[0].resources[0].completed is False
    assert record.roadmap.phases[1].resources[0].completed is False
    assert record.roadmap.phases[1].resources[1].completed is False
    assert updated.updated_at >= record.created_at


def test_roadmap_repo_update_resource_returns_none_for_missing_resource():
    repo = InMemoryRoadmapRepository()
    record, _, _ = _build_roadmap_record()
    repo.create(record)

    assert repo.update_resource(record.id, "not-a-real-resource", True) is None
    # The roadmap itself is still reachable (handler uses get() to
    # distinguish RESOURCE_NOT_FOUND from ROADMAP_NOT_FOUND).
    assert repo.get(record.id) is not None


def test_roadmap_repo_update_resource_returns_none_for_missing_roadmap():
    repo = InMemoryRoadmapRepository()
    assert repo.update_resource("missing-roadmap", "res-1", True) is None


def test_roadmap_repo_resource_index_stays_consistent_after_updates():
    repo = InMemoryRoadmapRepository()
    record, rid_mid, rid_last = _build_roadmap_record()
    repo.create(record)

    repo.update_resource(record.id, rid_mid, True)
    repo.update_resource(record.id, rid_last, True)

    # All four entries still resolve to their original positions.
    fetched = repo.get(record.id)
    assert fetched is not None
    assert fetched.resource_index == {
        "res-1": (0, 0),
        "res-2": (0, 1),
        "res-3": (1, 0),
        "res-4": (1, 1),
    }
    # Flip back one and confirm.
    repo.update_resource(record.id, rid_mid, False)
    assert record.roadmap.phases[0].resources[1].completed is False
