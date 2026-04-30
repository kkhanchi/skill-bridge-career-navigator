"""Integration tests for the roadmap endpoints.

Requirement reference: R5.1–R5.6.
"""

from __future__ import annotations

from app.core.models import JobPosting, UserProfile
from app.core.roadmap_generator import recalculate_match


VALID_PROFILE = {
    "name": "Test User",
    "skills": ["Python"],
    "experience_years": 1,
    "education": "BSc",
    "target_role": "Backend Developer",
}


def _chain(authenticated_client):
    """Helper: create profile -> analysis -> roadmap. Return all three payloads."""
    profile = authenticated_client.post("/api/v1/profiles", json=VALID_PROFILE).get_json()
    analysis = authenticated_client.post(
        "/api/v1/analyses",
        json={"profile_id": profile["id"], "job_id": "backend-developer"},
    ).get_json()
    roadmap = authenticated_client.post(
        "/api/v1/roadmaps",
        json={"analysis_id": analysis["id"]},
    ).get_json()
    return profile, analysis, roadmap


# ---------------------------------------------------------------------------
# POST /api/v1/roadmaps
# ---------------------------------------------------------------------------


def test_post_creates_roadmap_from_analysis(authenticated_client):
    _, analysis, roadmap = _chain(authenticated_client)

    assert roadmap["id"]
    assert roadmap["analysis_id"] == analysis["id"]
    # Three phases per generate_roadmap's _PHASE_LABELS.
    assert len(roadmap["phases"]) == 3
    # Every resource has a non-empty id and starts uncompleted.
    all_ids: list[str] = []
    for phase in roadmap["phases"]:
        for resource in phase["resources"]:
            assert resource["id"]
            assert resource["completed"] is False
            all_ids.append(resource["id"])
    # Ids are unique within a roadmap.
    assert len(set(all_ids)) == len(all_ids)


def test_post_returns_404_analysis_not_found(authenticated_client):
    response = authenticated_client.post(
        "/api/v1/roadmaps",
        json={"analysis_id": "does-not-exist"},
    )

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


def test_post_rejects_empty_analysis_id(authenticated_client):
    response = authenticated_client.post("/api/v1/roadmaps", json={"analysis_id": ""})

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_FAILED"


# ---------------------------------------------------------------------------
# PATCH /api/v1/roadmaps/{id}/resources/{resource_id}
# ---------------------------------------------------------------------------


def _pick_first_resource(roadmap: dict) -> dict:
    for phase in roadmap["phases"]:
        if phase["resources"]:
            return phase["resources"][0]
    raise AssertionError("Roadmap has no resources — test data issue")


def test_patch_resource_flips_completed_to_true(authenticated_client):
    _, _, roadmap = _chain(authenticated_client)
    first = _pick_first_resource(roadmap)

    response = authenticated_client.patch(
        f"/api/v1/roadmaps/{roadmap['id']}/resources/{first['id']}",
        json={"completed": True},
    )

    assert response.status_code == 200
    body = response.get_json()
    # Locate the patched resource in the returned roadmap.
    flipped = None
    for phase in body["phases"]:
        for resource in phase["resources"]:
            if resource["id"] == first["id"]:
                flipped = resource
    assert flipped is not None
    assert flipped["completed"] is True
    # updated_at should be at or after created_at.
    assert body["updated_at"] >= body["created_at"]


def test_patch_resource_can_flip_back_to_false(authenticated_client):
    _, _, roadmap = _chain(authenticated_client)
    first = _pick_first_resource(roadmap)
    rid = roadmap["id"]
    res_id = first["id"]

    # Flip to true, then back to false.
    authenticated_client.patch(f"/api/v1/roadmaps/{rid}/resources/{res_id}", json={"completed": True})
    response = authenticated_client.patch(
        f"/api/v1/roadmaps/{rid}/resources/{res_id}",
        json={"completed": False},
    )

    assert response.status_code == 200
    body = response.get_json()
    for phase in body["phases"]:
        for resource in phase["resources"]:
            if resource["id"] == res_id:
                assert resource["completed"] is False


def test_patch_returns_404_roadmap_not_found(authenticated_client):
    response = authenticated_client.patch(
        "/api/v1/roadmaps/does-not-exist/resources/also-bogus",
        json={"completed": True},
    )

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "ROADMAP_NOT_FOUND"


def test_patch_returns_404_resource_not_found_when_roadmap_exists(authenticated_client):
    _, _, roadmap = _chain(authenticated_client)

    response = authenticated_client.patch(
        f"/api/v1/roadmaps/{roadmap['id']}/resources/bogus-resource-id",
        json={"completed": True},
    )

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_patch_rejects_missing_completed_field(authenticated_client):
    _, _, roadmap = _chain(authenticated_client)
    first = _pick_first_resource(roadmap)

    response = authenticated_client.patch(
        f"/api/v1/roadmaps/{roadmap['id']}/resources/{first['id']}",
        json={},
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_FAILED"


# ---------------------------------------------------------------------------
# Monotonicity sanity check (not a Hypothesis property — that comes later)
# ---------------------------------------------------------------------------


def test_completion_monotonicity_sanity(authenticated_client):
    """Marking a resource complete must not decrease the recalculated match %.

    Non-Hypothesis form of R5.6: compute the recalculated match % before
    and after a PATCH; the post-PATCH value is >= the pre-PATCH value.
    """
    _, _, roadmap = _chain(authenticated_client)
    first = _pick_first_resource(roadmap)

    # Build domain objects for recalculate_match. Profile has one skill
    # (Python) from VALID_PROFILE; the job is backend-developer which
    # requires Python + SQL + REST APIs + Git.
    profile = UserProfile(
        name=VALID_PROFILE["name"],
        skills=list(VALID_PROFILE["skills"]),
        experience_years=VALID_PROFILE["experience_years"],
        education=VALID_PROFILE["education"],
        target_role=VALID_PROFILE["target_role"],
    )
    job_resp = authenticated_client.get("/api/v1/jobs/backend-developer").get_json()
    job = JobPosting(
        title=job_resp["title"],
        description=job_resp["description"],
        required_skills=list(job_resp["required_skills"]),
        preferred_skills=list(job_resp["preferred_skills"]),
        experience_level=job_resp["experience_level"],
    )

    # Helper: build a Roadmap domain object from the response body.
    def to_domain_roadmap(body):
        from app.core.models import LearningResource, Roadmap, RoadmapPhase
        return Roadmap(phases=[
            RoadmapPhase(
                label=phase["label"],
                resources=[
                    LearningResource(
                        name=res["name"],
                        skill=res["skill"],
                        resource_type=res["resource_type"],
                        estimated_hours=res["estimated_hours"],
                        url=res["url"],
                        completed=res["completed"],
                        id=res["id"],
                    )
                    for res in phase["resources"]
                ],
            )
            for phase in body["phases"]
        ])

    before_match = recalculate_match(profile, job, to_domain_roadmap(roadmap))

    patched = authenticated_client.patch(
        f"/api/v1/roadmaps/{roadmap['id']}/resources/{first['id']}",
        json={"completed": True},
    ).get_json()
    after_match = recalculate_match(profile, job, to_domain_roadmap(patched))

    assert after_match >= before_match
