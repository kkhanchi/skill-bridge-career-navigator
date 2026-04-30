"""Integration tests for POST /api/v1/auth/login.

Covers:
  200 happy path after register
  401 INVALID_CREDENTIALS on wrong password
  401 INVALID_CREDENTIALS on unknown email (same envelope — no account enumeration)
  200 case-insensitive email match (R2.6)
  429 RATE_LIMITED after 10 attempts per IP per minute

Requirement reference: R2, R13.3.
"""

from __future__ import annotations


_PASSWORD = "correct horse battery staple"


def _register(client, email="alice@example.com"):
    return client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _PASSWORD},
    )


def _login(client, email, password):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_login_returns_200_with_user_and_tokens(client):
    _register(client)
    response = _login(client, "alice@example.com", _PASSWORD)

    assert response.status_code == 200
    body = response.get_json()
    assert set(body.keys()) == {"user", "access", "refresh"}
    assert body["user"]["email"] == "alice@example.com"
    # Issuing login tokens doesn't revoke existing ones — existing
    # refresh tokens stay live (design §Open Question Q4 decision).


def test_login_accepts_email_with_different_case(client):
    _register(client, email="alice@example.com")
    response = _login(client, "ALICE@EXAMPLE.COM", _PASSWORD)
    assert response.status_code == 200
    assert response.get_json()["user"]["email"] == "alice@example.com"


def test_login_accepts_email_with_leading_whitespace(client):
    _register(client, email="alice@example.com")
    response = _login(client, "  alice@example.com  ", _PASSWORD)
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# 401 INVALID_CREDENTIALS — both failure branches surface identically
# ---------------------------------------------------------------------------


def test_login_wrong_password_returns_401(client):
    _register(client)
    response = _login(client, "alice@example.com", "wrongpass123")
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_unknown_email_returns_same_401(client):
    # No register call — the user simply doesn't exist.
    response = _login(client, "ghost@example.com", _PASSWORD)
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_both_failure_branches_produce_identical_envelope(client):
    _register(client)

    # Use an 8+ char wrong password so Pydantic lets it through — we
    # want the login logic's INVALID_CREDENTIALS path, not the
    # schema's VALIDATION_FAILED.
    wrong_pw = _login(client, "alice@example.com", "wrongpass123").get_json()
    unknown_email = _login(client, "ghost@example.com", _PASSWORD).get_json()

    # Same shape, same code, same message — no account enumeration leak.
    assert wrong_pw == unknown_email


# ---------------------------------------------------------------------------
# 400 VALIDATION_FAILED matrix (shared with register)
# ---------------------------------------------------------------------------


def test_login_rejects_short_password(client):
    response = _login(client, "alice@example.com", "short")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_FAILED"


def test_login_rejects_invalid_email(client):
    response = _login(client, "not-an-email", _PASSWORD)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_FAILED"


# ---------------------------------------------------------------------------
# 429 RATE_LIMITED
# ---------------------------------------------------------------------------


def test_login_rate_limits_after_10_attempts_per_minute(client):
    _register(client)

    # Burn through 10 valid logins.
    for _ in range(10):
        response = _login(client, "alice@example.com", _PASSWORD)
        assert response.status_code == 200

    # 11th -> 429. Envelope shape and correlation id preserved.
    response = _login(client, "alice@example.com", _PASSWORD)
    assert response.status_code == 429
    body = response.get_json()
    assert body["error"]["code"] == "RATE_LIMITED"
    assert response.headers["X-Correlation-ID"]
