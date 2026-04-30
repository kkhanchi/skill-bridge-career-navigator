"""Integration tests for the profile CRUD endpoints.

Covers every cell in the design's status-code matrix for profiles:

  201 POST success
  400 VALIDATION_FAILED (Pydantic)
  400 PROFILE_INVALID (core.ValueError)
  200 GET by id
  404 NOT_FOUND on GET/PATCH/DELETE
  200 PATCH with partial update
  204 DELETE
  400 PATCH with empty body (no fields)

Requirement reference: R1.1–R1.7, R6.1, R6.2, R6.3.
"""

from __future__ import annotations


VALID_PAYLOAD = {
    "name": "Test User",
    "skills": ["Python", "SQL"],
    "experience_years": 3,
    "education": "Bachelor's",
    "target_role": "Backend Developer",
}


def _create(authenticated_client, **overrides):
    payload = {**VALID_PAYLOAD, **overrides}
    response = authenticated_client.post("/api/v1/profiles", json=payload)
    return response


# ---------------------------------------------------------------------------
# POST /api/v1/profiles
# ---------------------------------------------------------------------------


def test_post_creates_profile_and_returns_201(authenticated_client):
    response = _create(authenticated_client)

    assert response.status_code == 201
    body = response.get_json()
    assert body["id"]
    assert body["name"] == "Test User"
    assert body["skills"] == ["Python", "SQL"]
    assert body["experience_years"] == 3
    assert body["target_role"] == "Backend Developer"
    assert "created_at" in body and "updated_at" in body
    assert response.headers["X-Correlation-ID"]


def test_post_rejects_empty_skills_with_validation_failed(authenticated_client):
    response = _create(authenticated_client, skills=[])

    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "VALIDATION_FAILED"
    # Pydantic error details are included for diagnostics.
    assert "details" in body["error"]
    assert "errors" in body["error"]["details"]


def test_post_rejects_unknown_field_with_validation_failed(authenticated_client):
    # Schema is strict (extra="forbid") — stray fields fail validation.
    response = _create(authenticated_client, shoe_size=12)

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_FAILED"


def test_post_rejects_negative_experience_years(authenticated_client):
    response = _create(authenticated_client, experience_years=-1)

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_FAILED"


def test_post_rejects_broken_json_body_with_validation_failed(authenticated_client):
    response = authenticated_client.post(
        "/api/v1/profiles",
        data="{not json",
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_FAILED"


def test_post_round_trip_get_returns_matching_body(authenticated_client):
    created = _create(authenticated_client).get_json()
    profile_id = created["id"]

    fetched = authenticated_client.get(f"/api/v1/profiles/{profile_id}")

    assert fetched.status_code == 200
    body = fetched.get_json()
    # Ignore audit timestamps (they may differ in representation).
    for field in ("id", "name", "skills", "experience_years", "education", "target_role"):
        assert body[field] == created[field]


# ---------------------------------------------------------------------------
# GET /api/v1/profiles/{id}
# ---------------------------------------------------------------------------


def test_get_returns_404_not_found_for_unknown_id(authenticated_client):
    response = authenticated_client.get("/api/v1/profiles/does-not-exist")

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "NOT_FOUND"
    assert response.headers["X-Correlation-ID"]


# ---------------------------------------------------------------------------
# PATCH /api/v1/profiles/{id}
# ---------------------------------------------------------------------------


def test_patch_applies_added_skills(authenticated_client):
    created = _create(authenticated_client).get_json()

    response = authenticated_client.patch(
        f"/api/v1/profiles/{created['id']}",
        json={"added_skills": ["Docker"]},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert "Docker" in body["skills"]
    # Original skills preserved, updated_at refreshed.
    assert set(body["skills"]) >= {"Python", "SQL", "Docker"}
    assert body["updated_at"] >= created["updated_at"]


def test_patch_applies_direct_field_override(authenticated_client):
    created = _create(authenticated_client).get_json()

    response = authenticated_client.patch(
        f"/api/v1/profiles/{created['id']}",
        json={"name": "Renamed User"},
    )

    assert response.status_code == 200
    assert response.get_json()["name"] == "Renamed User"


def test_patch_rejects_empty_body_with_validation_failed(authenticated_client):
    created = _create(authenticated_client).get_json()

    response = authenticated_client.patch(f"/api/v1/profiles/{created['id']}", json={})

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_FAILED"


def test_patch_returns_404_for_unknown_id(authenticated_client):
    response = authenticated_client.patch(
        "/api/v1/profiles/does-not-exist",
        json={"name": "Whoever"},
    )

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "NOT_FOUND"


def test_patch_surfaces_profile_invalid_on_domain_error(authenticated_client):
    """Removing every skill leaves the profile with 0 skills, which the
    core layer rejects as a domain-level validation error (400
    PROFILE_INVALID, distinct from schema-level VALIDATION_FAILED)."""
    created = _create(authenticated_client).get_json()

    response = authenticated_client.patch(
        f"/api/v1/profiles/{created['id']}",
        json={"removed_skills": created["skills"]},
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "PROFILE_INVALID"


# ---------------------------------------------------------------------------
# DELETE /api/v1/profiles/{id}
# ---------------------------------------------------------------------------


def test_delete_returns_204_and_removes_profile(authenticated_client):
    created = _create(authenticated_client).get_json()
    profile_id = created["id"]

    response = authenticated_client.delete(f"/api/v1/profiles/{profile_id}")

    assert response.status_code == 204
    # Body should be empty on 204.
    assert response.data in (b"", b"\n")

    # Subsequent GET returns 404.
    follow_up = authenticated_client.get(f"/api/v1/profiles/{profile_id}")
    assert follow_up.status_code == 404


def test_delete_returns_404_for_unknown_id(authenticated_client):
    response = authenticated_client.delete("/api/v1/profiles/does-not-exist")

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "NOT_FOUND"
