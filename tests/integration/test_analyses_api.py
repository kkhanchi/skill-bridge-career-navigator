"""Integration tests for the gap-analysis endpoints.

Requirement reference: R4.1–R4.6, R10.3.
"""

from __future__ import annotations


VALID_PROFILE = {
    "name": "Test User",
    "skills": ["Python", "SQL"],
    "experience_years": 2,
    "education": "BSc",
    "target_role": "Backend Developer",
}


def _create_profile(authenticated_client, **overrides):
    payload = {**VALID_PROFILE, **overrides}
    return authenticated_client.post("/api/v1/profiles", json=payload).get_json()


# ---------------------------------------------------------------------------
# POST /api/v1/analyses
# ---------------------------------------------------------------------------


def test_post_creates_analysis_with_gap_and_categorization(authenticated_client):
    profile = _create_profile(authenticated_client)

    response = authenticated_client.post(
        "/api/v1/analyses",
        json={"profile_id": profile["id"], "job_id": "backend-developer"},
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["id"]
    assert body["profile_id"] == profile["id"]
    assert body["job_id"] == "backend-developer"
    # Gap shape is complete.
    gap = body["gap"]
    for key in ("matched_required", "missing_required",
                "matched_preferred", "missing_preferred", "match_percentage"):
        assert key in gap
    assert 0 <= gap["match_percentage"] <= 100
    # Categorization shape is complete.
    cat = body["categorization"]
    assert set(cat.keys()) == {"groups", "summary", "is_fallback"}


def test_post_uses_fallback_categorizer_under_test_config(authenticated_client):
    """R10.3: TestConfig forces the FallbackCategorizer for determinism."""
    profile = _create_profile(authenticated_client)

    response = authenticated_client.post(
        "/api/v1/analyses",
        json={"profile_id": profile["id"], "job_id": "backend-developer"},
    )

    body = response.get_json()
    assert body["categorization"]["is_fallback"] is True


def test_post_returns_404_profile_not_found_for_unknown_profile(authenticated_client):
    response = authenticated_client.post(
        "/api/v1/analyses",
        json={"profile_id": "does-not-exist", "job_id": "backend-developer"},
    )

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "PROFILE_NOT_FOUND"


def test_post_checks_profile_before_job(authenticated_client):
    """R4.2 ordering: even if both ids are bogus, profile check runs first."""
    response = authenticated_client.post(
        "/api/v1/analyses",
        json={"profile_id": "missing-profile", "job_id": "missing-job"},
    )

    assert response.status_code == 404
    # Profile check fires first, so the error is PROFILE_NOT_FOUND — not JOB_NOT_FOUND.
    assert response.get_json()["error"]["code"] == "PROFILE_NOT_FOUND"


def test_post_returns_404_job_not_found_when_only_job_is_missing(authenticated_client):
    profile = _create_profile(authenticated_client)

    response = authenticated_client.post(
        "/api/v1/analyses",
        json={"profile_id": profile["id"], "job_id": "bogus-job"},
    )

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "JOB_NOT_FOUND"


def test_post_rejects_empty_profile_id(authenticated_client):
    response = authenticated_client.post(
        "/api/v1/analyses",
        json={"profile_id": "", "job_id": "backend-developer"},
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_FAILED"


def test_post_rejects_missing_body_keys(authenticated_client):
    response = authenticated_client.post("/api/v1/analyses", json={"profile_id": "only-one"})

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_FAILED"


# ---------------------------------------------------------------------------
# GET /api/v1/analyses/{id}
# ---------------------------------------------------------------------------


def test_get_returns_stored_analysis(authenticated_client):
    profile = _create_profile(authenticated_client)
    created = authenticated_client.post(
        "/api/v1/analyses",
        json={"profile_id": profile["id"], "job_id": "backend-developer"},
    ).get_json()

    response = authenticated_client.get(f"/api/v1/analyses/{created['id']}")

    assert response.status_code == 200
    body = response.get_json()
    assert body["id"] == created["id"]
    assert body["gap"]["match_percentage"] == created["gap"]["match_percentage"]


def test_get_returns_404_analysis_not_found_for_unknown_id(authenticated_client):
    response = authenticated_client.get("/api/v1/analyses/does-not-exist")

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "ANALYSIS_NOT_FOUND"
