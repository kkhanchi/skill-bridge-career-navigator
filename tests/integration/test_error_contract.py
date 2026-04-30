"""Cross-cutting tests for the Error_Envelope contract.

Complements the per-resource integration tests by exercising the
framework-level error paths that apply to every endpoint.

Requirement reference: R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, R7.3.
"""

from __future__ import annotations

import pytest
from flask import Blueprint


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
    # Flask-raised HTTPException mappings used by R6.5. These aren't in
    # the R6.2 closed set literally, but R6.5 requires a mapping — the
    # design doc calls this out as an open decision we'll document in
    # the error-contract ADR.
    "METHOD_NOT_ALLOWED",
    "UNSUPPORTED_MEDIA_TYPE",
}


def _assert_envelope(body: dict, expected_code: str | None = None) -> None:
    """Assert the response body matches the Error_Envelope contract."""
    assert isinstance(body, dict), f"body is not a dict: {body!r}"
    assert set(body.keys()) == {"error"}, f"extra top-level keys: {body.keys()}"
    error = body["error"]
    assert isinstance(error, dict)
    assert isinstance(error.get("code"), str) and error["code"]
    assert isinstance(error.get("message"), str) and error["message"]
    if expected_code is not None:
        assert error["code"] == expected_code


# ---------------------------------------------------------------------------
# Flask HTTPException paths (R6.5)
# ---------------------------------------------------------------------------


def test_unknown_route_returns_not_found_envelope(client):
    response = client.get("/api/v1/this-does-not-exist")

    assert response.status_code == 404
    _assert_envelope(response.get_json(), expected_code="NOT_FOUND")
    assert response.headers["X-Correlation-ID"]


def test_method_not_allowed_returns_envelope(client):
    # /health only accepts GET; DELETE should 405.
    response = client.delete("/health")

    assert response.status_code == 405
    body = response.get_json()
    _assert_envelope(body)
    assert body["error"]["code"] in VALID_ERROR_CODES
    assert response.headers["X-Correlation-ID"]


# ---------------------------------------------------------------------------
# Body-parsing paths (R6.3)
# ---------------------------------------------------------------------------


def test_broken_json_body_becomes_validation_failed(authenticated_client):
    response = authenticated_client.post(
        "/api/v1/profiles",
        data="{not valid json",
        content_type="application/json",
    )

    assert response.status_code == 400
    body = response.get_json()
    _assert_envelope(body, expected_code="VALIDATION_FAILED")
    # R6.3: Pydantic error list is surfaced in details.errors.
    assert "details" in body["error"]
    assert "errors" in body["error"]["details"]
    assert isinstance(body["error"]["details"]["errors"], list)


def test_non_json_content_type_still_becomes_validation_failed(authenticated_client):
    # No Content-Type, plain string body — request.get_json(silent=True)
    # returns None which the validator treats as {} and fails required
    # field checks (VALIDATION_FAILED), not 415.
    response = authenticated_client.post("/api/v1/profiles", data="not even json")

    assert response.status_code == 400
    _assert_envelope(response.get_json(), expected_code="VALIDATION_FAILED")


# ---------------------------------------------------------------------------
# Unhandled exception -> INTERNAL_ERROR (R6.4)
# ---------------------------------------------------------------------------


@pytest.fixture
def app_with_boom_route():
    """A test-only app that includes a route which deliberately raises.

    Exercises the catch-all Exception handler without polluting the
    production blueprint registration. Uses TestConfig so the
    FallbackCategorizer is forced.
    """
    from app import create_app

    app = create_app("test")

    boom_bp = Blueprint("boom", __name__)

    @boom_bp.get("/boom")
    def boom():
        raise RuntimeError("deliberate failure for testing")

    app.register_blueprint(boom_bp)
    return app


def test_unhandled_exception_returns_500_internal_error(app_with_boom_route):
    client = app_with_boom_route.test_client()

    response = client.get("/boom")

    assert response.status_code == 500
    body = response.get_json()
    _assert_envelope(body, expected_code="INTERNAL_ERROR")
    # R6.4: generic message, does not leak the raised exception's text.
    assert body["error"]["message"] == "An unexpected error occurred"
    assert "deliberate failure" not in body["error"]["message"]
    # Correlation id still present on 500 responses (R6.6).
    assert response.headers["X-Correlation-ID"]


# ---------------------------------------------------------------------------
# R6.6: envelope + X-Correlation-ID present on every >=400 response
# ---------------------------------------------------------------------------


def test_error_codes_used_by_framework_are_in_the_valid_set(authenticated_client):
    """Sweep the endpoints that emit each error code and confirm each
    reported code is in our known set. Catches accidental typos when
    new error codes are introduced later."""
    sweep = [
        # (method, path, body or None, expected status >= 400)
        ("POST", "/api/v1/profiles", {}, 400),                             # VALIDATION_FAILED
        ("GET", "/api/v1/profiles/missing", None, 404),                    # NOT_FOUND
        ("PATCH", "/api/v1/profiles/missing", {"name": "X"}, 404),         # NOT_FOUND
        ("DELETE", "/api/v1/profiles/missing", None, 404),                 # NOT_FOUND
        ("GET", "/api/v1/jobs/missing-slug", None, 404),                   # JOB_NOT_FOUND
        ("GET", "/api/v1/analyses/missing", None, 404),                    # ANALYSIS_NOT_FOUND
        ("POST", "/api/v1/analyses", {"profile_id": "p", "job_id": "j"}, 404),  # PROFILE_NOT_FOUND
        ("POST", "/api/v1/roadmaps", {"analysis_id": "nope"}, 404),        # ANALYSIS_NOT_FOUND
    ]

    for method, path, body, expected_status in sweep:
        if body is None:
            response = authenticated_client.open(method=method, path=path)
        else:
            response = authenticated_client.open(method=method, path=path, json=body)

        assert response.status_code == expected_status, (
            f"{method} {path} expected {expected_status}, got {response.status_code}"
        )
        payload = response.get_json()
        _assert_envelope(payload)
        assert payload["error"]["code"] in VALID_ERROR_CODES, (
            f"{method} {path} returned unknown code {payload['error']['code']!r}"
        )
        assert response.headers["X-Correlation-ID"]
