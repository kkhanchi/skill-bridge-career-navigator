"""Integration tests for GET /api/v1/auth/me.

Covers:
  200 with the correct user on a valid access token
  401 AUTH_REQUIRED when the Authorization header is missing or malformed
  401 TOKEN_EXPIRED on an expired access token (via the now= seam)
  401 TOKEN_INVALID when the access token refers to a deleted user

Requirement reference: R5.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.auth.tokens import encode_access_token


_PASSWORD = "correct horse battery staple"


def _register(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "alice@example.com", "password": _PASSWORD},
    )
    assert response.status_code == 201
    return response.get_json()


# ---------------------------------------------------------------------------
# 200 happy path
# ---------------------------------------------------------------------------


def test_me_returns_200_with_current_user(client):
    tokens = _register(client)

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['access']}"},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert set(body.keys()) == {"user"}
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["id"] == tokens["user"]["id"]
    # password_hash must never leak into the response.
    assert "password_hash" not in body["user"]


# ---------------------------------------------------------------------------
# 401 AUTH_REQUIRED — header-level failures
# ---------------------------------------------------------------------------


def test_me_without_authorization_header_is_auth_required(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "AUTH_REQUIRED"


def test_me_with_non_bearer_header_is_auth_required(client):
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Basic admin:hunter2"}
    )
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "AUTH_REQUIRED"


# ---------------------------------------------------------------------------
# 401 TOKEN_EXPIRED
# ---------------------------------------------------------------------------


def test_me_with_expired_access_token_is_token_expired(app, client):
    tokens = _register(client)
    user_id = tokens["user"]["id"]

    with app.app_context():
        in_the_past = datetime.now(timezone.utc) - timedelta(hours=2)
        expired = encode_access_token(user_id, now=in_the_past)

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired}"},
    )
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "TOKEN_EXPIRED"


# ---------------------------------------------------------------------------
# 401 TOKEN_INVALID — valid token for a user that no longer exists
# ---------------------------------------------------------------------------


def test_me_with_token_for_unknown_user_is_token_invalid(app, client):
    # Mint an access token for a user id that was never registered.
    # The token cryptographically verifies but user_repo.get_by_id
    # returns None -> 401 TOKEN_INVALID.
    with app.app_context():
        token = encode_access_token(uuid4().hex)

    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "TOKEN_INVALID"


def test_me_with_malformed_token_is_token_invalid(client):
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not.a.jwt"}
    )
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "TOKEN_INVALID"
