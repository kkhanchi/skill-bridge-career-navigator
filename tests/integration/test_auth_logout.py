"""Integration tests for POST /api/v1/auth/logout.

Logout's contract is deliberately defensive:
  204 on valid refresh (revokes the jti)
  204 on already-revoked refresh (idempotent, R4.4)
  204 on malformed refresh (can't decode, nothing to revoke — still 204)
  400 VALIDATION_FAILED only when the body is shape-wrong (missing refresh field)

Cross-endpoint assertions:
  After logout, presenting the same refresh to /refresh returns 401 TOKEN_INVALID.
  Access tokens are NOT invalidated by logout — /me still works with the
  pre-logout access token until it expires naturally (R4.5).

Requirement reference: R4, R4.4, R4.5.
"""

from __future__ import annotations


_PASSWORD = "correct horse battery staple"


def _register(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "alice@example.com", "password": _PASSWORD},
    )
    assert response.status_code == 201
    return response.get_json()


# ---------------------------------------------------------------------------
# 204 happy path
# ---------------------------------------------------------------------------


def test_logout_with_valid_refresh_returns_204(client):
    tokens = _register(client)

    response = client.post(
        "/api/v1/auth/logout", json={"refresh": tokens["refresh"]}
    )
    assert response.status_code == 204
    # 204 No Content: body is empty. Flask's test client returns b"".
    assert response.data == b""


def test_logout_revokes_the_refresh_token(client):
    tokens = _register(client)

    client.post("/api/v1/auth/logout", json={"refresh": tokens["refresh"]})

    # Presenting the same refresh to /refresh afterwards returns
    # TOKEN_INVALID — jti is revoked.
    response = client.post(
        "/api/v1/auth/refresh", json={"refresh": tokens["refresh"]}
    )
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "TOKEN_INVALID"


def test_logout_is_idempotent(client):
    """R4.4: calling /logout twice still returns 204 the second time."""
    tokens = _register(client)

    first = client.post(
        "/api/v1/auth/logout", json={"refresh": tokens["refresh"]}
    )
    assert first.status_code == 204

    # Already-revoked refresh -> still 204 (defensive UX).
    second = client.post(
        "/api/v1/auth/logout", json={"refresh": tokens["refresh"]}
    )
    assert second.status_code == 204


def test_logout_with_malformed_refresh_still_returns_204(client):
    """Malformed token can't be decoded -> nothing to revoke -> 204."""
    response = client.post(
        "/api/v1/auth/logout", json={"refresh": "not.a.jwt"}
    )
    assert response.status_code == 204


# ---------------------------------------------------------------------------
# Access tokens survive logout (R4.5)
# ---------------------------------------------------------------------------


def test_logout_does_not_invalidate_access_token(client):
    """R4.5: logout revokes refresh only. Access tokens live until exp."""
    tokens = _register(client)

    # Log out.
    logout = client.post(
        "/api/v1/auth/logout", json={"refresh": tokens["refresh"]}
    )
    assert logout.status_code == 204

    # The pre-logout access token still works on /me — it stays valid
    # until its natural exp (15 minutes from issue).
    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['access']}"},
    )
    assert me.status_code == 200
    assert me.get_json()["user"]["email"] == "alice@example.com"


# ---------------------------------------------------------------------------
# 400 VALIDATION_FAILED — the only non-204 path
# ---------------------------------------------------------------------------


def test_logout_missing_field_is_validation_failed(client):
    response = client.post("/api/v1/auth/logout", json={})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_FAILED"


def test_logout_empty_refresh_string_is_validation_failed(client):
    response = client.post("/api/v1/auth/logout", json={"refresh": ""})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_FAILED"
