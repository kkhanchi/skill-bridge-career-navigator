"""SQL-backend integration tests.

Drives the full HTTP stack (Flask app factory + blueprints + SQL
repositories + session hooks) against an in-memory SQLite database.
Parallel to the Phase 1 memory-backed integration tests — the same
contracts, different backend.

Three groups of tests:

1. CRUD round-trips per resource (profile, job, analysis, roadmap)
   covering the status-code matrix.
2. The `flag_modified` persistence check — PATCH a resource in one
   request, read it back in a fresh request, confirm the flag
   actually landed on disk (catches the silent-drop bug R7.1 / R7.3
   exist to prevent).
3. SQL pagination (R8.4): 30 seeded jobs, 3 pages at limit=10,
   concatenation equals the full filtered list.

Requirement reference: R2.6, R6.1, R6.2, R6.4, R7.1, R7.2, R7.3,
R8.1, R8.2, R8.3, R8.4.
"""

from __future__ import annotations

from uuid import uuid4

from app.core.models import JobPosting
from app.db.models import JobORM, RoadmapORM
from app.db.session import get_db_session  # noqa: F401  - for clarity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


VALID_PROFILE = {
    "name": "Test User",
    "skills": ["Python", "SQL"],
    "experience_years": 2,
    "education": "BSc",
    "target_role": "Backend Developer",
}


def _seed_job(sql_app, **overrides) -> str:
    """Insert a JobORM row directly through the SQL repo + session
    hooks. Returns the row's slug id.
    """
    payload = {
        "id": overrides.get("id", "backend-developer"),
        "title": overrides.get("title", "Backend Developer"),
        "description": overrides.get("description", "Build APIs"),
        "required_skills": overrides.get(
            "required_skills", ["Python", "SQL", "REST APIs", "Git"]
        ),
        "preferred_skills": overrides.get(
            "preferred_skills", ["Docker", "AWS"]
        ),
        "experience_level": overrides.get("experience_level", "Mid"),
    }
    # Use a short-lived session bound to the per-test engine; not inside
    # a request, so we build one explicitly rather than via the hook.
    ext = sql_app.extensions["skillbridge"]
    with ext.session_factory() as session:
        session.add(JobORM(**payload))
        session.commit()
    return payload["id"]


# ---------------------------------------------------------------------------
# Profile CRUD round-trip
# ---------------------------------------------------------------------------


def test_profile_crud_round_trip_on_sql_backend(sql_client):
    # POST -> 201 and id is a uuid4 hex.
    created = sql_client.post("/api/v1/profiles", json=VALID_PROFILE)
    assert created.status_code == 201
    body = created.get_json()
    profile_id = body["id"]
    assert len(profile_id) == 32

    # GET -> 200 with equal fields.
    fetched = sql_client.get(f"/api/v1/profiles/{profile_id}")
    assert fetched.status_code == 200
    for field in ("name", "skills", "experience_years", "education", "target_role"):
        assert fetched.get_json()[field] == body[field]

    # PATCH -> 200 and updated_at refreshed.
    patched = sql_client.patch(
        f"/api/v1/profiles/{profile_id}",
        json={"added_skills": ["Docker"]},
    )
    assert patched.status_code == 200
    assert "Docker" in patched.get_json()["skills"]
    assert patched.get_json()["updated_at"] >= body["updated_at"]

    # DELETE -> 204 then 404.
    deleted = sql_client.delete(f"/api/v1/profiles/{profile_id}")
    assert deleted.status_code == 204
    gone = sql_client.get(f"/api/v1/profiles/{profile_id}")
    assert gone.status_code == 404


def test_profile_get_returns_404_for_unknown_id(sql_client):
    response = sql_client.get(f"/api/v1/profiles/{uuid4().hex}")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# Job listing + lookup
# ---------------------------------------------------------------------------


def test_get_job_by_slug_returns_200_after_seed(sql_client, sql_app):
    _seed_job(sql_app)

    response = sql_client.get("/api/v1/jobs/backend-developer")
    assert response.status_code == 200
    body = response.get_json()
    assert body["id"] == "backend-developer"
    assert body["title"] == "Backend Developer"


def test_get_job_by_unknown_slug_returns_404(sql_client):
    response = sql_client.get("/api/v1/jobs/not-a-real-job")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "JOB_NOT_FOUND"


def test_list_jobs_empty_catalog_returns_empty_envelope(sql_client):
    response = sql_client.get("/api/v1/jobs")
    assert response.status_code == 200
    body = response.get_json()
    assert body["items"] == []
    assert body["meta"]["total"] == 0
    assert body["meta"]["pages"] == 0


# ---------------------------------------------------------------------------
# Full analysis + roadmap chain
# ---------------------------------------------------------------------------


def test_analysis_roadmap_chain_on_sql_backend(sql_client, sql_app):
    _seed_job(sql_app)

    # Create profile.
    profile = sql_client.post("/api/v1/profiles", json=VALID_PROFILE).get_json()
    assert profile["id"]

    # Create analysis.
    analysis = sql_client.post(
        "/api/v1/analyses",
        json={"profile_id": profile["id"], "job_id": "backend-developer"},
    ).get_json()
    assert analysis["id"]
    assert analysis["gap"]["match_percentage"] == 50  # Python, SQL matched; REST APIs, Git missing

    # Create roadmap.
    roadmap_resp = sql_client.post(
        "/api/v1/roadmaps",
        json={"analysis_id": analysis["id"]},
    )
    assert roadmap_resp.status_code == 201
    roadmap = roadmap_resp.get_json()
    assert len(roadmap["phases"]) == 3
    # Every resource has a non-empty uuid id.
    all_ids: list[str] = []
    for phase in roadmap["phases"]:
        for resource in phase["resources"]:
            assert resource["id"]
            assert resource["completed"] is False
            all_ids.append(resource["id"])
    assert len(set(all_ids)) == len(all_ids)


# ---------------------------------------------------------------------------
# R7.1 / R7.3 — flag_modified persistence check
# ---------------------------------------------------------------------------


def test_patch_resource_persists_across_sessions(sql_client, sql_app):
    """Catches the missing-flag_modified bug.

    Without ``flag_modified(row, "phases")``, the PATCH returns 200 in
    the same request (because the in-memory row reflects the change),
    but on commit SQLAlchemy doesn't detect the nested mutation and
    the change is silently dropped. This test fails in that scenario
    because it re-reads through a FRESH session bypassing Flask's
    request context.
    """
    _seed_job(sql_app)

    # Full chain to get a roadmap id + resource id.
    profile = sql_client.post("/api/v1/profiles", json=VALID_PROFILE).get_json()
    analysis = sql_client.post(
        "/api/v1/analyses",
        json={"profile_id": profile["id"], "job_id": "backend-developer"},
    ).get_json()
    roadmap = sql_client.post(
        "/api/v1/roadmaps",
        json={"analysis_id": analysis["id"]},
    ).get_json()

    # Pick the first resource and flip it.
    first_resource = None
    for phase in roadmap["phases"]:
        if phase["resources"]:
            first_resource = phase["resources"][0]
            break
    assert first_resource is not None

    patched = sql_client.patch(
        f"/api/v1/roadmaps/{roadmap['id']}/resources/{first_resource['id']}",
        json={"completed": True},
    )
    assert patched.status_code == 200

    # Re-read DIRECTLY from a fresh session — bypasses anything cached
    # on the current request. Walk the persisted phases JSON to find
    # the flipped resource.
    ext = sql_app.extensions["skillbridge"]
    with ext.session_factory() as session:
        row = session.get(RoadmapORM, roadmap["id"])
        assert row is not None
        flipped = None
        for phase in row.phases:
            for resource in phase.get("resources", []):
                if resource["id"] == first_resource["id"]:
                    flipped = resource
        assert flipped is not None
        assert flipped["completed"] is True, (
            "Resource completed flag was lost on commit — flag_modified missing"
        )


def test_patch_roadmap_returns_404_for_missing_roadmap(sql_client):
    response = sql_client.patch(
        f"/api/v1/roadmaps/{uuid4().hex}/resources/any",
        json={"completed": True},
    )
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "ROADMAP_NOT_FOUND"


def test_patch_roadmap_resource_not_found_distinguished_from_missing_roadmap(
    sql_client, sql_app
):
    _seed_job(sql_app)
    profile = sql_client.post("/api/v1/profiles", json=VALID_PROFILE).get_json()
    analysis = sql_client.post(
        "/api/v1/analyses",
        json={"profile_id": profile["id"], "job_id": "backend-developer"},
    ).get_json()
    roadmap = sql_client.post(
        "/api/v1/roadmaps", json={"analysis_id": analysis["id"]},
    ).get_json()

    response = sql_client.patch(
        f"/api/v1/roadmaps/{roadmap['id']}/resources/totally-bogus",
        json={"completed": True},
    )
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "RESOURCE_NOT_FOUND"


# ---------------------------------------------------------------------------
# SQL pagination (R8.4)
# ---------------------------------------------------------------------------


def _seed_many_jobs(sql_app, count: int) -> None:
    """Insert ``count`` jobs with deterministic slugs j-000, j-001, …."""
    ext = sql_app.extensions["skillbridge"]
    with ext.session_factory() as session:
        for i in range(count):
            session.add(JobORM(
                id=f"j-{i:03d}",
                title=f"Role {i}",
                description=f"desc {i}",
                required_skills=["Python"],
                preferred_skills=[],
                experience_level="Mid",
            ))
        session.commit()


def test_pagination_partitions_filtered_set(sql_client, sql_app):
    _seed_many_jobs(sql_app, count=30)

    # Walk pages 1-3 at limit=10; concat should equal the full set.
    seen_ids: list[str] = []
    seen_totals: set[int] = set()
    pages_seen: set[int] = set()
    for page in (1, 2, 3):
        response = sql_client.get(f"/api/v1/jobs?limit=10&page={page}")
        assert response.status_code == 200
        body = response.get_json()
        seen_ids.extend(item["id"] for item in body["items"])
        seen_totals.add(body["meta"]["total"])
        pages_seen.add(body["meta"]["pages"])

    assert len(seen_ids) == 30
    assert len(set(seen_ids)) == 30  # no duplicates (R8.4)
    assert seen_totals == {30}       # total invariant across pages
    assert pages_seen == {3}         # pages == ceil(30/10) invariant

    # Ordering is deterministic (R8.3): ORDER BY id ASC.
    assert seen_ids == sorted(seen_ids)


def test_pagination_beyond_last_page_returns_empty_items(sql_client, sql_app):
    _seed_many_jobs(sql_app, count=5)

    response = sql_client.get("/api/v1/jobs?limit=10&page=99")
    assert response.status_code == 200
    body = response.get_json()
    assert body["items"] == []
    assert body["meta"]["total"] == 5
    assert body["meta"]["pages"] == 1
