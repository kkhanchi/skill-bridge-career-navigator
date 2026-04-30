"""Multi-tenant isolation across profiles / analyses / roadmaps.

Two authenticated clients on the same app (userA and userB). For
every resource userA creates, userB's token MUST receive 404 on
every read / mutation — including POSTs that reference userA's id.
Cross-tenant access collapses to the same 404 code a genuinely
missing resource would produce (ADR-015 anti-enumeration).

Requirement reference: R6.
"""

from __future__ import annotations


VALID_PROFILE = {
    "name": "Alice",
    "skills": ["Python", "SQL"],
    "experience_years": 3,
    "education": "Bachelor's",
    "target_role": "Backend Developer",
}


# ---------------------------------------------------------------------------
# Profile isolation
# ---------------------------------------------------------------------------


def test_user_b_cannot_read_user_a_profile(
    authenticated_client, second_authenticated_client
):
    created = authenticated_client.post("/api/v1/profiles", json=VALID_PROFILE)
    assert created.status_code == 201
    profile_id = created.get_json()["id"]

    response = second_authenticated_client.get(f"/api/v1/profiles/{profile_id}")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "NOT_FOUND"


def test_user_b_cannot_patch_user_a_profile(
    authenticated_client, second_authenticated_client
):
    created = authenticated_client.post("/api/v1/profiles", json=VALID_PROFILE)
    profile_id = created.get_json()["id"]

    response = second_authenticated_client.patch(
        f"/api/v1/profiles/{profile_id}", json={"name": "Hacked"}
    )
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "NOT_FOUND"


def test_user_b_cannot_delete_user_a_profile(
    authenticated_client, second_authenticated_client
):
    created = authenticated_client.post("/api/v1/profiles", json=VALID_PROFILE)
    profile_id = created.get_json()["id"]

    response = second_authenticated_client.delete(f"/api/v1/profiles/{profile_id}")
    assert response.status_code == 404

    # And the profile is still there from userA's perspective.
    check = authenticated_client.get(f"/api/v1/profiles/{profile_id}")
    assert check.status_code == 200


# ---------------------------------------------------------------------------
# Analysis isolation
# ---------------------------------------------------------------------------


def test_user_b_cannot_create_analysis_referencing_user_a_profile(
    authenticated_client, second_authenticated_client
):
    created = authenticated_client.post("/api/v1/profiles", json=VALID_PROFILE)
    profile_id = created.get_json()["id"]

    response = second_authenticated_client.post(
        "/api/v1/analyses",
        json={"profile_id": profile_id, "job_id": "backend-developer"},
    )
    # R6.4: profile owned by userA looks missing to userB.
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "PROFILE_NOT_FOUND"


def test_user_b_cannot_read_user_a_analysis(
    authenticated_client, second_authenticated_client
):
    # userA creates a profile + analysis.
    profile = authenticated_client.post("/api/v1/profiles", json=VALID_PROFILE).get_json()
    analysis = authenticated_client.post(
        "/api/v1/analyses",
        json={"profile_id": profile["id"], "job_id": "backend-developer"},
    ).get_json()

    response = second_authenticated_client.get(
        f"/api/v1/analyses/{analysis['id']}"
    )
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


# ---------------------------------------------------------------------------
# Roadmap isolation
# ---------------------------------------------------------------------------


def test_user_b_cannot_create_roadmap_from_user_a_analysis(
    authenticated_client, second_authenticated_client
):
    profile = authenticated_client.post("/api/v1/profiles", json=VALID_PROFILE).get_json()
    analysis = authenticated_client.post(
        "/api/v1/analyses",
        json={"profile_id": profile["id"], "job_id": "backend-developer"},
    ).get_json()

    response = second_authenticated_client.post(
        "/api/v1/roadmaps", json={"analysis_id": analysis["id"]}
    )
    # R6.5: userA's analysis looks missing to userB.
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


def test_user_b_cannot_patch_resource_in_user_a_roadmap(
    authenticated_client, second_authenticated_client
):
    # Full chain on userA's side.
    profile = authenticated_client.post("/api/v1/profiles", json=VALID_PROFILE).get_json()
    analysis = authenticated_client.post(
        "/api/v1/analyses",
        json={"profile_id": profile["id"], "job_id": "backend-developer"},
    ).get_json()
    roadmap = authenticated_client.post(
        "/api/v1/roadmaps", json={"analysis_id": analysis["id"]}
    ).get_json()

    # Find any resource inside userA's roadmap so we can target it.
    resource_id = None
    for phase in roadmap["phases"]:
        if phase["resources"]:
            resource_id = phase["resources"][0]["id"]
            break
    # It's possible the gap is empty (profile has everything) — in
    # that case there are no resources to target and the test is
    # degenerate. Guard against that by skipping.
    if resource_id is None:
        import pytest
        pytest.skip("gap was empty; no resources to probe for isolation")

    response = second_authenticated_client.patch(
        f"/api/v1/roadmaps/{roadmap['id']}/resources/{resource_id}",
        json={"completed": True},
    )
    # userB can't see the roadmap at all, so this is ROADMAP_NOT_FOUND,
    # not RESOURCE_NOT_FOUND — the ownership gate runs first.
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "ROADMAP_NOT_FOUND"


# ---------------------------------------------------------------------------
# Envelope shape sanity — cross-tenant 404s don't leak fields
# ---------------------------------------------------------------------------


def test_cross_tenant_404_response_body_leaks_nothing(
    authenticated_client, second_authenticated_client
):
    """R6.6: error bodies carry only {code, message} — no resource fields."""
    created = authenticated_client.post("/api/v1/profiles", json=VALID_PROFILE)
    profile_id = created.get_json()["id"]

    body = second_authenticated_client.get(
        f"/api/v1/profiles/{profile_id}"
    ).get_json()

    # Plain envelope. No fields borrowed from userA's profile.
    assert set(body.keys()) == {"error"}
    assert set(body["error"].keys()) <= {"code", "message", "details"}
    # None of userA's profile values leak into the error body.
    assert "Alice" not in body["error"]["message"]
    assert "Python" not in str(body["error"])


# ---------------------------------------------------------------------------
# Round-trip invariant — userA can always see their own resources
# ---------------------------------------------------------------------------


def test_user_a_always_sees_their_own_profile(authenticated_client):
    created = authenticated_client.post("/api/v1/profiles", json=VALID_PROFILE)
    profile_id = created.get_json()["id"]

    fetched = authenticated_client.get(f"/api/v1/profiles/{profile_id}")
    assert fetched.status_code == 200
    assert fetched.get_json()["id"] == profile_id
