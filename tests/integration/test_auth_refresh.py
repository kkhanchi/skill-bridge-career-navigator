"""Integration tests for POST /api/v1/auth/refresh.

Covers the rotation contract (R3.7):
  200 happy path -> old jti revoked, new refresh differs from the old
  401 TOKEN_INVALID when the SAME refresh is presented twice
  401 TOKEN_INVALID when an access token is presented as refresh
  401 TOKEN_INVALID on malformed tokens
  401 TOKEN_EXPIRED on manually-forged expired refresh
  400 VALIDATION_FAILED on missing field
  429 RATE_LIMITED after 30 requests per minute

Requirement reference: R3, R3.7.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.auth.tokens import encode_access_token, encode_refresh_token


_PASSWORD = "correct horse battery staple"


def _register_and_get_tokens(client):
    """Register a user and return the initial {user, access, refresh} body."""
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "alice@example.com", "password": _PASSWORD},
    )
    assert response.status_code == 201
    return response.get_json()


# ---------------------------------------------------------------------------
# Happy path + rotation
# ---------------------------------------------------------------------------


def test_refresh_returns_200_with_new_token_pair(client):
    tokens = _register_and_get_tokens(client)

    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh": tokens["refresh"]},
    )

    assert response.status_code == 200
    body = response.get_json()
    # /refresh returns only tokens, no user object.
    assert set(body.keys()) == {"access", "refresh"}
    # New refresh must be a different string from the old one —
    # otherwise rotation isn't actually rotating.
    assert body["refresh"] != tokens["refresh"]
    # Access can differ (fresh jti + iat) but MUST be a valid JWT shape.
    assert body["access"].count(".") == 2


def test_refresh_is_one_shot(client):
    """R3.7 Token_Rotation: the old refresh is dead after one use."""
    tokens = _register_and_get_tokens(client)

    # First call — rotates the pair.
    first = client.post(
        "/api/v1/auth/refresh",
        json={"refresh": tokens["refresh"]},
    )
    assert first.status_code == 200

    # Second call with the SAME refresh — must be rejected.
    second = client.post(
        "/api/v1/auth/refresh",
        json={"refresh": tokens["refresh"]},
    )
    assert second.status_code == 401
    assert second.get_json()["error"]["code"] == "TOKEN_INVALID"


def test_refresh_chain_produces_working_tokens(client):
    """Rotating multiple times yields usable access tokens at each step."""
    tokens = _register_and_get_tokens(client)
    current_refresh = tokens["refresh"]

    for _ in range(3):
        response = client.post(
            "/api/v1/auth/refresh", json={"refresh": current_refresh}
        )
        assert response.status_code == 200
        body = response.get_json()
        # Each minted access token is usable on /me.
        me = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {body['access']}"},
        )
        assert me.status_code == 200
        current_refresh = body["refresh"]


# ---------------------------------------------------------------------------
# 401 TOKEN_INVALID paths
# ---------------------------------------------------------------------------


def test_refresh_with_access_token_is_token_invalid(client):
    tokens = _register_and_get_tokens(client)

    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh": tokens["access"]},  # wrong type
    )
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "TOKEN_INVALID"


def test_refresh_with_malformed_token_is_token_invalid(client):
    response = client.post(
        "/api/v1/auth/refresh", json={"refresh": "not.a.jwt"}
    )
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "TOKEN_INVALID"


# ---------------------------------------------------------------------------
# 401 TOKEN_EXPIRED — forge an expired refresh via the now= seam
# ---------------------------------------------------------------------------


def test_refresh_with_expired_token_is_token_expired(app, client):
    tokens = _register_and_get_tokens(client)

    # Need the user id to mint an expired token; extract it from the
    # register response.
    user_id = tokens["user"]["id"]

    with app.app_context():
        in_the_past = datetime.now(timezone.utc) - timedelta(days=30)
        expired_refresh, _, _ = encode_refresh_token(user_id, now=in_the_past)

    response = client.post(
        "/api/v1/auth/refresh", json={"refresh": expired_refresh}
    )
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "TOKEN_EXPIRED"


# ---------------------------------------------------------------------------
# 400 VALIDATION_FAILED
# ---------------------------------------------------------------------------


def test_refresh_missing_field_is_validation_failed(client):
    response = client.post("/api/v1/auth/refresh", json={})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_FAILED"


def test_refresh_empty_string_is_validation_failed(client):
    response = client.post("/api/v1/auth/refresh", json={"refresh": ""})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_FAILED"


# ---------------------------------------------------------------------------
# 429 RATE_LIMITED — 30/minute threshold
# ---------------------------------------------------------------------------


def test_refresh_rate_limits_after_30_requests(client):
    # We don't need 30 valid refreshes — the rate limiter decorator
    # runs before body validation, so 30 malformed requests also
    # burn the quota. Saves test time versus minting 30 valid chains.
    for _ in range(30):
        response = client.post(
            "/api/v1/auth/refresh", json={"refresh": "not.a.jwt"}
        )
        # Each individual request is either 401 TOKEN_INVALID (bad
        # token passes through body validation) — it's the count that
        # matters, not the per-request outcome.
        assert response.status_code in (400, 401)

    # 31st hits the limit.
    response = client.post(
        "/api/v1/auth/refresh", json={"refresh": "not.a.jwt"}
    )
    assert response.status_code == 429
    assert response.get_json()["error"]["code"] == "RATE_LIMITED"
