"""Unit tests for the ``@require_auth`` decorator.

Builds a minimal test-only app with one decorated route so the tests
cover the decorator's behaviour in isolation from the profile /
analysis / roadmap handlers (those are exercised end-to-end in the
integration suite).

Covers every cell in the design's failure matrix plus the happy path:

- No Authorization header           -> 401 AUTH_REQUIRED
- Header without the ``Bearer `` prefix -> 401 AUTH_REQUIRED
- ``Bearer `` with empty token      -> 401 AUTH_REQUIRED
- Expired access token              -> 401 TOKEN_EXPIRED
- Malformed token                   -> 401 TOKEN_INVALID
- Refresh token as access           -> 401 TOKEN_INVALID
- Valid token for deleted user      -> 401 TOKEN_INVALID
- Valid token                       -> 200 + ``current_user`` kwarg

Requirement reference: R5.2, R5.3, R5.4, R13.7.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from flask import Blueprint, jsonify

from app import create_app
from app.auth.decorator import require_auth
from app.auth.tokens import encode_access_token, encode_refresh_token


# ---------------------------------------------------------------------------
# Fixture: app with one decorated route that echoes current_user
# ---------------------------------------------------------------------------


@pytest.fixture
def decorated_app():
    """Fresh test app carrying a single ``@require_auth`` echo route."""
    app = create_app("test")

    bp = Blueprint("probe", __name__)

    @bp.get("/probe")
    @require_auth
    def probe(*, current_user):
        return jsonify({"user_id": current_user.id, "email": current_user.email}), 200

    app.register_blueprint(bp)
    return app


@pytest.fixture
def decorated_client(decorated_app):
    return decorated_app.test_client()


@pytest.fixture
def registered_user(decorated_app):
    """Register a user and return its UserRecord."""
    ext = decorated_app.extensions["skillbridge"]
    pw = ext.hasher.hash("correct horse battery staple")
    with decorated_app.test_request_context():
        decorated_app.preprocess_request()
        user = ext.user_repo.create(email="probe@example.com", password_hash=pw)
        decorated_app.do_teardown_request(None)
    return user


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_valid_access_token_injects_current_user(
    decorated_app, decorated_client, registered_user
):
    with decorated_app.app_context():
        token = encode_access_token(registered_user.id)

    response = decorated_client.get(
        "/probe",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["user_id"] == registered_user.id
    assert body["email"] == "probe@example.com"


# ---------------------------------------------------------------------------
# Header-level failures (AUTH_REQUIRED)
# ---------------------------------------------------------------------------


def test_no_authorization_header_is_auth_required(decorated_client):
    response = decorated_client.get("/probe")
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "AUTH_REQUIRED"


def test_header_without_bearer_prefix_is_auth_required(decorated_client):
    response = decorated_client.get(
        "/probe",
        headers={"Authorization": "Basic some-credentials"},
    )
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "AUTH_REQUIRED"


def test_empty_bearer_token_is_auth_required(decorated_client):
    # The decorator strips whitespace after "Bearer " — a header with
    # only the prefix (and/or whitespace after it) must surface as
    # AUTH_REQUIRED, not TOKEN_INVALID (we haven't looked at a token).
    response = decorated_client.get(
        "/probe",
        headers={"Authorization": "Bearer   "},
    )
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "AUTH_REQUIRED"


# ---------------------------------------------------------------------------
# Token-level failures (TOKEN_EXPIRED / TOKEN_INVALID)
# ---------------------------------------------------------------------------


def test_expired_access_token_is_token_expired(
    decorated_app, decorated_client, registered_user
):
    with decorated_app.app_context():
        in_the_past = datetime.now(timezone.utc) - timedelta(hours=2)
        token = encode_access_token(registered_user.id, now=in_the_past)

    response = decorated_client.get(
        "/probe", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "TOKEN_EXPIRED"


def test_malformed_token_is_token_invalid(decorated_client):
    response = decorated_client.get(
        "/probe", headers={"Authorization": "Bearer not.a.jwt"}
    )
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "TOKEN_INVALID"


def test_refresh_token_presented_as_access_is_token_invalid(
    decorated_app, decorated_client, registered_user
):
    with decorated_app.app_context():
        token, _, _ = encode_refresh_token(registered_user.id)

    response = decorated_client.get(
        "/probe", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "TOKEN_INVALID"


def test_wrong_secret_token_is_token_invalid(decorated_client):
    # Forge a well-formed access-type JWT signed with a different secret.
    claims = {
        "sub": uuid4().hex,
        "iat": 0,
        "exp": 9_999_999_999,
        "jti": uuid4().hex,
        "type": "access",
    }
    forged = jwt.encode(claims, "some-other-secret", algorithm="HS256")
    response = decorated_client.get(
        "/probe", headers={"Authorization": f"Bearer {forged}"}
    )
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "TOKEN_INVALID"


def test_token_for_unknown_user_is_token_invalid(decorated_app, decorated_client):
    # Mint a valid access token for a user id that was never registered.
    with decorated_app.app_context():
        token = encode_access_token(uuid4().hex)

    response = decorated_client.get(
        "/probe", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "TOKEN_INVALID"


# ---------------------------------------------------------------------------
# Error envelope shape sanity
# ---------------------------------------------------------------------------


def test_auth_failure_response_follows_envelope_contract(decorated_client):
    response = decorated_client.get("/probe")
    body = response.get_json()
    # Same envelope shape the Phase 1 contract test asserts — the
    # decorator must not bypass the global error handler.
    assert set(body.keys()) == {"error"}
    assert isinstance(body["error"]["code"], str) and body["error"]["code"]
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    # Correlation id is still attached to auth failures.
    assert response.headers["X-Correlation-ID"]
