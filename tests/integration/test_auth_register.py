"""Integration tests for POST /api/v1/auth/register.

Covers the design's status-code matrix:
  201 happy path -> body has user + access + refresh
  400 VALIDATION_FAILED for malformed bodies
  409 EMAIL_TAKEN for duplicate (case-insensitive)
  429 RATE_LIMITED after 5 requests from the same IP in an hour
Also checks email normalization and that the response never leaks
password_hash.

Requirement reference: R1, R13.3.
"""

from __future__ import annotations


VALID = {"email": "alice@example.com", "password": "correct horse battery staple"}


def _register(client, **overrides):
    payload = {**VALID, **overrides}
    return client.post("/api/v1/auth/register", json=payload)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_register_returns_201_with_user_access_refresh(client):
    response = _register(client)

    assert response.status_code == 201
    body = response.get_json()
    # Envelope contract: user object + both tokens, nothing else.
    assert set(body.keys()) == {"user", "access", "refresh"}
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["id"]
    assert "created_at" in body["user"]
    # password_hash must never appear in any response body (R2.5).
    assert "password_hash" not in body["user"]
    # Tokens are non-empty JWT strings. Shape-only check — tokens are
    # verified end-to-end by the login + /me path.
    assert body["access"].count(".") == 2
    assert body["refresh"].count(".") == 2


def test_register_normalizes_email_case_and_whitespace(client):
    response = _register(client, email="  Alice@Example.COM  ")

    assert response.status_code == 201
    # Email in the response is lower-cased + stripped. Any future
    # login that uses the raw input must resolve to this canonical
    # form (tested in test_auth_login.py).
    assert response.get_json()["user"]["email"] == "alice@example.com"


# ---------------------------------------------------------------------------
# 400 VALIDATION_FAILED matrix
# ---------------------------------------------------------------------------


def test_register_rejects_short_password(client):
    response = _register(client, password="short")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_FAILED"


def test_register_rejects_password_over_128_chars(client):
    response = _register(client, password="a" * 129)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_FAILED"


def test_register_rejects_invalid_email_format(client):
    response = _register(client, email="not-an-email")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_FAILED"


def test_register_rejects_whitespace_only_password(client):
    response = _register(client, password="        ")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_FAILED"


def test_register_rejects_unknown_fields(client):
    # STRICT_MODEL_CONFIG forbids extra keys.
    response = client.post(
        "/api/v1/auth/register",
        json={**VALID, "shoe_size": 12},
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_FAILED"


# ---------------------------------------------------------------------------
# 409 EMAIL_TAKEN — duplicate detection is case-insensitive
# ---------------------------------------------------------------------------


def test_register_rejects_duplicate_email_with_409(client):
    first = _register(client)
    assert first.status_code == 201

    second = _register(client)
    assert second.status_code == 409
    assert second.get_json()["error"]["code"] == "EMAIL_TAKEN"


def test_register_duplicate_detection_is_case_insensitive(client):
    first = _register(client, email="alice@example.com")
    assert first.status_code == 201

    second = _register(client, email="ALICE@EXAMPLE.COM")
    assert second.status_code == 409
    assert second.get_json()["error"]["code"] == "EMAIL_TAKEN"


# ---------------------------------------------------------------------------
# 429 RATE_LIMITED after 5 requests
# ---------------------------------------------------------------------------


def test_register_rate_limits_after_5_requests_per_hour(client):
    # First five with unique emails all succeed (201).
    for i in range(5):
        response = _register(client, email=f"u{i}@example.com")
        assert response.status_code == 201, (i, response.get_json())

    # Sixth hits the limit. The body has to match the envelope shape.
    response = _register(client, email="u6@example.com")
    assert response.status_code == 429
    body = response.get_json()
    assert body["error"]["code"] == "RATE_LIMITED"
    # Correlation id still present on 429 — error handler contract (R14.1).
    assert response.headers["X-Correlation-ID"]
