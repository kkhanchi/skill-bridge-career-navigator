"""Hypothesis property-based tests for Phase 1 correctness invariants.

Each property maps to a single acceptance criterion in
``requirements.md``; the docstring names the requirement.

Settings note: these properties drive the Flask test client over HTTP,
so each example is comparatively expensive. ``max_examples=30`` keeps
the suite under a second while still surfacing counterexamples for any
regression in the contract. If a property fails, Hypothesis will
minimise the input and print it.

Requirement reference: R1.8, R3.7, R4.7, R5.6, R6.6, R6.2, R7.3.
"""

from __future__ import annotations

from math import ceil

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from app import create_app


VALID_ERROR_CODES = {
    "VALIDATION_FAILED",
    "PROFILE_INVALID",
    "NOT_FOUND",
    "PROFILE_NOT_FOUND",
    "JOB_NOT_FOUND",
    "ANALYSIS_NOT_FOUND",
    "ROADMAP_NOT_FOUND",
    "RESOURCE_NOT_FOUND",
    "INTERNAL_ERROR",
    "METHOD_NOT_ALLOWED",
    "UNSUPPORTED_MEDIA_TYPE",
}


# ---------------------------------------------------------------------------
# Fresh app per example — property tests can't reuse a function-scoped
# fixture inside @given, so we build one directly.
# ---------------------------------------------------------------------------


def _fresh_client():
    app = create_app("test")
    return app.test_client()


# Hypothesis often doesn't play nicely with function-scoped fixtures; the
# HealthCheck suppression below covers that and the "data generation is
# slow" noise that the Flask round-trip triggers on some machines.
PROPERTY_SETTINGS = settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[
        HealthCheck.function_scoped_fixture,
        HealthCheck.too_slow,
    ],
)


# ---------------------------------------------------------------------------
# Hypothesis strategies for valid profile payloads
# ---------------------------------------------------------------------------


# Skills drawn from a small alphabet so duplicates (and thus dedup) are
# meaningful, but every string is a valid non-empty skill token.
_skill_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"), whitelist_characters=" -/"
    ),
    min_size=1,
    max_size=30,
).filter(lambda s: s.strip() != "" and len(s.strip()) <= 100)


@st.composite
def valid_profile_payload(draw) -> dict:
    """Generate a profile payload guaranteed to pass schema + domain validation.

    - name: 1..200 chars, non-empty after strip
    - skills: 1..30 distinct skills (dedup happens domain-side, so we
      produce a set-like list to avoid empty-after-dedup surprises)
    - experience_years: 0..80
    - education: 0..200 chars
    - target_role: 1..200 chars, non-empty after strip
    """
    name = draw(st.text(min_size=1, max_size=200).filter(lambda s: s.strip() != ""))
    # Use a set to avoid duplicates, then back to a sorted list for determinism.
    raw_skills = draw(st.sets(_skill_strategy, min_size=1, max_size=30))
    skills = sorted(raw_skills)[:30]
    # Filter size again post-sort (the set may shrink below min_size=1
    # in rare paths — safeguard).
    if len(skills) == 0:
        skills = ["Python"]
    experience_years = draw(st.integers(min_value=0, max_value=80))
    education = draw(st.text(min_size=0, max_size=200))
    target_role = draw(
        st.text(min_size=1, max_size=200).filter(lambda s: s.strip() != "")
    )
    return {
        "name": name,
        "skills": skills,
        "experience_years": experience_years,
        "education": education,
        "target_role": target_role,
    }


# ---------------------------------------------------------------------------
# Property 1: Profile round-trip (validates R1.8)
# ---------------------------------------------------------------------------


@PROPERTY_SETTINGS
@given(payload=valid_profile_payload())
def test_profile_round_trip_property(payload):
    """POST then GET returns a body equal to the POST response (ignoring timestamps).

    Property 1: Profile round-trip — Validates R1.8.
    """
    client = _fresh_client()

    post_response = client.post("/api/v1/profiles", json=payload)
    assert post_response.status_code == 201, post_response.get_json()
    created = post_response.get_json()

    get_response = client.get(f"/api/v1/profiles/{created['id']}")
    assert get_response.status_code == 200
    fetched = get_response.get_json()

    ignored = {"created_at", "updated_at"}
    assert {k: v for k, v in created.items() if k not in ignored} == \
           {k: v for k, v in fetched.items() if k not in ignored}


# ---------------------------------------------------------------------------
# Property 2: Pagination partition (validates R3.7)
# ---------------------------------------------------------------------------


_keyword_strategy = st.one_of(
    st.just(""),
    st.sampled_from(["developer", "engineer", "data", "cloud", "zzz"]),
)
_skill_filter_strategy = st.one_of(
    st.just(""),
    st.sampled_from(["Python", "SQL", "AWS", "Docker", "nonexistent-skill"]),
)


@PROPERTY_SETTINGS
@given(
    keyword=_keyword_strategy,
    skill=_skill_filter_strategy,
    limit=st.integers(min_value=1, max_value=100),
)
def test_pagination_partition_property(keyword, skill, limit):
    """Concatenating every page at limit L equals the full filtered list.

    Also asserts: meta.total is invariant across pages, meta.pages ==
    ceil(total/limit) for total > 0 else 0, ids are unique across the
    concatenation.

    Property 2: Pagination partition — Validates R3.7.
    """
    client = _fresh_client()

    # Reference: the full filtered list via a single large-limit call.
    ref_response = client.get(
        f"/api/v1/jobs?keyword={keyword}&skill={skill}&limit=100&page=1"
    )
    assert ref_response.status_code == 200
    reference_items = ref_response.get_json()["items"]
    expected_total = len(reference_items)
    expected_pages = ceil(expected_total / limit) if expected_total > 0 else 0

    # Concatenate every page at the test's limit.
    concatenated: list[dict] = []
    totals_seen: set[int] = set()
    page = 1
    while page <= max(expected_pages, 1):
        response = client.get(
            f"/api/v1/jobs?keyword={keyword}&skill={skill}&limit={limit}&page={page}"
        )
        assert response.status_code == 200
        body = response.get_json()
        concatenated.extend(body["items"])
        totals_seen.add(body["meta"]["total"])
        assert body["meta"]["pages"] == expected_pages
        page += 1

    # total is invariant across pages.
    assert totals_seen == {expected_total}

    # Concatenation equals reference (order preserved).
    assert [item["id"] for item in concatenated] == [
        item["id"] for item in reference_items
    ]

    # No duplicates across pages.
    ids = [item["id"] for item in concatenated]
    assert len(set(ids)) == len(ids)


# ---------------------------------------------------------------------------
# Property 3: Gap analysis case-insensitivity (validates R4.7)
# ---------------------------------------------------------------------------


# For this property we re-case the *skills*, keeping everything else equal.
_casing_transform_strategy = st.sampled_from(["identity", "upper", "lower", "title"])


def _retype_skills(skills: list[str], mode: str) -> list[str]:
    if mode == "identity":
        return list(skills)
    if mode == "upper":
        return [s.upper() for s in skills]
    if mode == "lower":
        return [s.lower() for s in skills]
    if mode == "title":
        return [s.title() for s in skills]
    raise ValueError(mode)


@PROPERTY_SETTINGS
@given(
    payload=valid_profile_payload(),
    transform=_casing_transform_strategy,
)
def test_gap_analysis_case_insensitivity_property(payload, transform):
    """Recasing a profile's skills does not change the gap match percentage.

    Property 3: Gap analysis case-insensitivity — Validates R4.7.
    """
    client = _fresh_client()

    # Profile 1: the payload as-is.
    p1 = client.post("/api/v1/profiles", json=payload)
    assert p1.status_code == 201
    id1 = p1.get_json()["id"]

    # Profile 2: identical payload but with skills re-cased.
    recased = {**payload, "skills": _retype_skills(payload["skills"], transform)}
    # Guard: if the transform produces a skill that would violate the
    # <=100 char limit or become empty (unlikely for our alphabets but
    # cheap to check), skip — Hypothesis will try another example.
    for skill in recased["skills"]:
        if not skill.strip() or len(skill.strip()) > 100:
            pytest.skip("transform produced an invalid skill token")

    p2 = client.post("/api/v1/profiles", json=recased)
    assert p2.status_code == 201, p2.get_json()
    id2 = p2.get_json()["id"]

    # Run both analyses against the same fixed job.
    a1 = client.post(
        "/api/v1/analyses",
        json={"profile_id": id1, "job_id": "backend-developer"},
    ).get_json()
    a2 = client.post(
        "/api/v1/analyses",
        json={"profile_id": id2, "job_id": "backend-developer"},
    ).get_json()

    assert a1["gap"]["match_percentage"] == a2["gap"]["match_percentage"]


# ---------------------------------------------------------------------------
# Property 4: Completion monotonicity (validates R5.6)
# ---------------------------------------------------------------------------


@PROPERTY_SETTINGS
@given(payload=valid_profile_payload())
def test_completion_monotonicity_property(payload):
    """Marking a resource completed never decreases the recalculated match %.

    Property 4: Roadmap completion monotonicity — Validates R5.6.
    """
    from app.core.models import JobPosting, LearningResource, Roadmap, RoadmapPhase, UserProfile
    from app.core.roadmap_generator import recalculate_match

    client = _fresh_client()

    profile_resp = client.post("/api/v1/profiles", json=payload)
    assert profile_resp.status_code == 201
    profile_id = profile_resp.get_json()["id"]

    analysis = client.post(
        "/api/v1/analyses",
        json={"profile_id": profile_id, "job_id": "backend-developer"},
    ).get_json()

    roadmap_resp = client.post("/api/v1/roadmaps", json={"analysis_id": analysis["id"]})
    assert roadmap_resp.status_code == 201
    roadmap = roadmap_resp.get_json()

    # Find any resource. If the gap is empty, skip this example.
    first_resource = None
    for phase in roadmap["phases"]:
        if phase["resources"]:
            first_resource = phase["resources"][0]
            break
    if first_resource is None:
        pytest.skip("empty gap -> no resources to mark complete")

    job_body = client.get("/api/v1/jobs/backend-developer").get_json()
    job = JobPosting(
        title=job_body["title"],
        description=job_body["description"],
        required_skills=list(job_body["required_skills"]),
        preferred_skills=list(job_body["preferred_skills"]),
        experience_level=job_body["experience_level"],
    )
    profile = UserProfile(
        name=payload["name"],
        skills=list(payload["skills"]),
        experience_years=payload["experience_years"],
        education=payload["education"],
        target_role=payload["target_role"],
    )

    def to_domain(body):
        return Roadmap(phases=[
            RoadmapPhase(
                label=phase["label"],
                resources=[
                    LearningResource(
                        name=r["name"], skill=r["skill"],
                        resource_type=r["resource_type"],
                        estimated_hours=r["estimated_hours"], url=r["url"],
                        completed=r["completed"], id=r["id"],
                    )
                    for r in phase["resources"]
                ],
            )
            for phase in body["phases"]
        ])

    before = recalculate_match(profile, job, to_domain(roadmap))

    patched = client.patch(
        f"/api/v1/roadmaps/{roadmap['id']}/resources/{first_resource['id']}",
        json={"completed": True},
    ).get_json()

    after = recalculate_match(profile, job, to_domain(patched))
    assert after >= before


# ---------------------------------------------------------------------------
# Property 5: Error envelope shape (validates R6.6)
# ---------------------------------------------------------------------------


# Strategy: generate arbitrary JSON objects and fling them at every
# write endpoint. We don't care what they contain — any response >= 400
# must match the envelope contract.
_arbitrary_json_value = st.recursive(
    st.one_of(
        st.none(),
        st.booleans(),
        st.integers(),
        st.floats(allow_nan=False, allow_infinity=False),
        st.text(max_size=20),
    ),
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(min_size=1, max_size=10), children, max_size=5),
    ),
    max_leaves=10,
)
_malformed_body_strategy = st.dictionaries(
    st.text(min_size=1, max_size=10),
    _arbitrary_json_value,
    max_size=5,
)
_write_endpoints = st.sampled_from([
    ("POST", "/api/v1/profiles"),
    ("PATCH", "/api/v1/profiles/some-random-id"),
    ("POST", "/api/v1/resume/parse"),
    ("POST", "/api/v1/analyses"),
    ("POST", "/api/v1/roadmaps"),
])


@PROPERTY_SETTINGS
@given(endpoint=_write_endpoints, payload=_malformed_body_strategy)
def test_error_envelope_shape_property(endpoint, payload):
    """Every >=400 response matches the Error_Envelope shape and carries X-Correlation-ID.

    Property 5: Error envelope shape — Validates R6.6.
    """
    client = _fresh_client()
    method, path = endpoint

    response = client.open(method=method, path=path, json=payload)

    # If Hypothesis happens to generate a valid payload that Pydantic
    # accepts, the response can be a legitimate success or a 404 with
    # the right shape. We only make assertions on >=400 responses.
    if response.status_code < 400:
        return

    body = response.get_json()
    assert isinstance(body, dict), f"body is not a dict: {body!r}"
    assert set(body.keys()) == {"error"}, f"extra top-level keys: {body.keys()}"
    error = body["error"]
    assert isinstance(error, dict)
    assert isinstance(error.get("code"), str) and error["code"]
    assert isinstance(error.get("message"), str) and error["message"]
    assert error["code"] in VALID_ERROR_CODES, (
        f"unknown error code {error['code']!r} from {method} {path}"
    )
    assert response.headers["X-Correlation-ID"]
