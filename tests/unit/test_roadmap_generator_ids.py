"""Unit tests for roadmap resource-id assignment and id-based completion.

Validates that :func:`generate_roadmap` stamps each emitted resource
with a unique uuid, that :func:`mark_completed_by_id` flips the right
resource and leaves siblings intact, and that :func:`mark_completed`
preserves ids when rebuilding the roadmap (required so repository
``resource_index`` stays valid across Streamlit's name-based flow).

Requirement reference: R5.1, R5.3, R12.2.
"""

from __future__ import annotations

import pytest

from app.core.models import GapResult, LearningResource, Roadmap, RoadmapPhase
from app.core.roadmap_generator import (
    generate_roadmap,
    mark_completed,
    mark_completed_by_id,
)


def _gap_with(missing_required: list[str], missing_preferred: list[str] | None = None) -> GapResult:
    return GapResult(
        matched_required=[],
        matched_preferred=[],
        missing_required=missing_required,
        missing_preferred=missing_preferred or [],
        match_percentage=0,
    )


def test_generate_roadmap_assigns_unique_ids_for_mapped_resources(sample_resources):
    gap = _gap_with(["REST APIs", "Docker", "AWS"])

    roadmap = generate_roadmap(gap, sample_resources)

    all_resources = [r for phase in roadmap.phases for r in phase.resources]
    assert len(all_resources) >= 3
    ids = [r.id for r in all_resources]
    # Every resource has a non-empty id.
    assert all(r.id for r in all_resources)
    # Ids are unique within a roadmap.
    assert len(set(ids)) == len(ids)


def test_generate_roadmap_assigns_unique_ids_for_placeholder_resources():
    # No matching resources in the catalog -> placeholder path.
    gap = _gap_with(["Obscure Skill A", "Obscure Skill B"])

    roadmap = generate_roadmap(gap, resources=[])

    all_resources = [r for phase in roadmap.phases for r in phase.resources]
    assert len(all_resources) == 2
    assert all(r.id for r in all_resources)
    assert len({r.id for r in all_resources}) == 2


def test_generate_roadmap_empty_gap_returns_empty_phases():
    roadmap = generate_roadmap(_gap_with([]), resources=[])
    assert all(len(phase.resources) == 0 for phase in roadmap.phases)


def test_mark_completed_by_id_flips_target_only():
    r1 = LearningResource(name="A", skill="Python", resource_type="c",
                          estimated_hours=1, url="u", id="id-1")
    r2 = LearningResource(name="B", skill="SQL", resource_type="c",
                          estimated_hours=1, url="u", id="id-2")
    r3 = LearningResource(name="C", skill="Docker", resource_type="c",
                          estimated_hours=1, url="u", id="id-3")
    roadmap = Roadmap(phases=[
        RoadmapPhase(label="Phase 1", resources=[r1, r2]),
        RoadmapPhase(label="Phase 2", resources=[r3]),
    ])

    updated = mark_completed_by_id(roadmap, "id-2")

    # Only id-2 is completed in the returned roadmap.
    flat = [r for phase in updated.phases for r in phase.resources]
    completed = {r.id: r.completed for r in flat}
    assert completed == {"id-1": False, "id-2": True, "id-3": False}
    # Original is unchanged (the function returns a new Roadmap).
    assert r2.completed is False


def test_mark_completed_by_id_raises_for_unknown_id():
    roadmap = Roadmap(phases=[RoadmapPhase(
        label="Phase 1",
        resources=[LearningResource(
            name="A", skill="Python", resource_type="c",
            estimated_hours=1, url="u", id="id-1")],
    )])

    with pytest.raises(KeyError):
        mark_completed_by_id(roadmap, "missing-id")


def test_mark_completed_preserves_ids_for_streamlit_flow():
    # The Streamlit UI still uses mark_completed(roadmap, name). The
    # rebuilt Roadmap must keep the original ids so any repository
    # index built before the rebuild remains valid.
    r1 = LearningResource(name="A", skill="Python", resource_type="c",
                          estimated_hours=1, url="u", id="keep-1")
    r2 = LearningResource(name="B", skill="SQL", resource_type="c",
                          estimated_hours=1, url="u", id="keep-2")
    roadmap = Roadmap(phases=[RoadmapPhase(label="Phase 1", resources=[r1, r2])])

    updated = mark_completed(roadmap, "A")

    flat = [r for phase in updated.phases for r in phase.resources]
    assert {r.id for r in flat} == {"keep-1", "keep-2"}
    assert {r.id: r.completed for r in flat} == {"keep-1": True, "keep-2": False}
