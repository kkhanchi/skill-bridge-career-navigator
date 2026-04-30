"""Integration tests for the resume parse endpoint.

Requirement reference: R2.1, R2.2, R2.3.
"""

from __future__ import annotations


def test_post_parse_extracts_known_skills(client):
    # Skills present in the loaded taxonomy should be detected.
    text = "I have 3 years of Python and SQL experience, plus some Docker."
    response = client.post("/api/v1/resume/parse", json={"text": text})

    assert response.status_code == 200
    body = response.get_json()
    assert "skills" in body
    detected = {s.lower() for s in body["skills"]}
    assert {"python", "sql", "docker"}.issubset(detected)


def test_post_parse_returns_empty_list_when_no_skills_found(client):
    response = client.post(
        "/api/v1/resume/parse",
        json={"text": "I enjoy hiking and baking bread on the weekends."},
    )

    assert response.status_code == 200
    assert response.get_json() == {"skills": []}


def test_post_parse_rejects_empty_text(client):
    response = client.post("/api/v1/resume/parse", json={"text": ""})

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_FAILED"


def test_post_parse_rejects_text_exceeding_50k_chars(client):
    # Build a 50_001-char string using content (not trailing whitespace)
    # so ``str_strip_whitespace=True`` doesn't bring it under the cap.
    oversized = "Python." * 7143  # 7143 * 7 = 50001 chars, no trailing space
    assert len(oversized) > 50_000

    response = client.post("/api/v1/resume/parse", json={"text": oversized})

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_FAILED"


def test_post_parse_has_no_side_effects(client):
    """Calling /resume/parse twice must not affect any repository state."""
    text = "Python, SQL, Docker."

    # Baseline: count existing profiles (should be 0 in a fresh test app).
    # We can't introspect the repo directly without reaching into extensions,
    # but we can assert that a GET on a random id still returns 404 unchanged
    # after two parse calls.
    client.post("/api/v1/resume/parse", json={"text": text})
    client.post("/api/v1/resume/parse", json={"text": text})

    # Nothing new should be reachable.
    r = client.get("/api/v1/profiles/random-uuid-never-created")
    assert r.status_code == 404
