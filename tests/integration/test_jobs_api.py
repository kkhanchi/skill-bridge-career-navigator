"""Integration tests for the job catalog endpoints.

Requirement reference: R3.1–R3.6, R9.1.
"""

from __future__ import annotations


# Helper to make the response shape introspectable in one line.
def _fetch(client, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = "/api/v1/jobs" + (f"?{qs}" if qs else "")
    return client.get(url)


# ---------------------------------------------------------------------------
# GET /api/v1/jobs — list + pagination
# ---------------------------------------------------------------------------


def test_list_default_pagination_returns_all_jobs(client):
    response = _fetch(client)

    assert response.status_code == 200
    body = response.get_json()
    assert body["meta"]["page"] == 1
    assert body["meta"]["limit"] == 20
    assert body["meta"]["total"] == 10
    assert body["meta"]["pages"] == 1
    assert len(body["items"]) == 10
    # Every item has the required fields.
    for item in body["items"]:
        assert set(item.keys()) == {
            "id", "title", "description",
            "required_skills", "preferred_skills", "experience_level",
        }


def test_list_limit_1_yields_pages_equal_to_total(client):
    response = _fetch(client, limit=1)

    body = response.get_json()
    assert body["meta"]["limit"] == 1
    assert body["meta"]["total"] == 10
    assert body["meta"]["pages"] == 10
    assert len(body["items"]) == 1


def test_list_limit_100_still_ok_on_small_catalog(client):
    response = _fetch(client, limit=100)

    assert response.status_code == 200
    body = response.get_json()
    assert body["meta"]["limit"] == 100
    assert len(body["items"]) == 10


def test_list_rejects_limit_zero(client):
    response = _fetch(client, limit=0)

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_FAILED"


def test_list_rejects_limit_over_100(client):
    response = _fetch(client, limit=101)

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_FAILED"


def test_list_rejects_page_zero(client):
    response = _fetch(client, page=0)

    assert response.status_code == 400


def test_list_page_beyond_last_returns_empty_items(client):
    response = _fetch(client, page=99, limit=20)

    assert response.status_code == 200
    body = response.get_json()
    assert body["items"] == []
    # total and pages still reflect the actual dataset.
    assert body["meta"]["total"] == 10
    assert body["meta"]["pages"] == 1


def test_list_empty_filter_result_has_zero_total_and_pages(client):
    response = _fetch(client, keyword="zzz-no-such-role")

    assert response.status_code == 200
    body = response.get_json()
    assert body["items"] == []
    assert body["meta"]["total"] == 0
    assert body["meta"]["pages"] == 0


def test_list_keyword_filter_matches_title(client):
    response = _fetch(client, keyword="developer")

    body = response.get_json()
    titles = {item["title"] for item in body["items"]}
    # "Backend Developer", "Frontend Developer", "Full Stack Developer",
    # "Mobile Developer" all contain "developer".
    assert titles == {
        "Backend Developer",
        "Frontend Developer",
        "Full Stack Developer",
        "Mobile Developer",
    }


def test_list_skill_filter_matches_required_skill(client):
    response = _fetch(client, skill="Python")

    body = response.get_json()
    # Every returned job lists Python in required_skills.
    for item in body["items"]:
        assert "Python" in item["required_skills"]


# ---------------------------------------------------------------------------
# GET /api/v1/jobs/{id}
# ---------------------------------------------------------------------------


def test_get_by_slug_returns_200(client):
    # 'Backend Developer' -> 'backend-developer' per the slugify rules.
    response = client.get("/api/v1/jobs/backend-developer")

    assert response.status_code == 200
    body = response.get_json()
    assert body["id"] == "backend-developer"
    assert body["title"] == "Backend Developer"


def test_get_by_unknown_slug_returns_404(client):
    response = client.get("/api/v1/jobs/not-a-real-job")

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "JOB_NOT_FOUND"


def test_get_unknown_slug_response_still_carries_correlation_id(client):
    response = client.get("/api/v1/jobs/not-a-real-job")
    assert response.headers["X-Correlation-ID"]
