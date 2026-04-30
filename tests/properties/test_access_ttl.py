"""Property: access tokens mint with the configured TTL (R8.8).

For any valid registration, the access token's ``exp`` claim equals
``iat + ACCESS_TTL_SECONDS`` exactly. Drives register -> /me to
confirm the token is both usable AND carries the expected TTL.

A complementary property uses the ``now=`` seam on ``encode_access_token``
to forge a boundary-case token (``exp == now``) and assert it is
rejected as TOKEN_EXPIRED — verifying the decoder's exp handling is
strictly-less-than, not less-than-or-equal.

Requirement reference: R8.8.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hypothesis import HealthCheck, given, settings
from hypothesis.strategies import text

from app import create_app
from app.auth.tokens import decode_token, encode_access_token


_PROPERTY_SETTINGS = settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)

_password_strategy = (
    text(min_size=8, max_size=40).filter(lambda s: s.strip() != "")
)


def _fresh_app_and_client():
    app = create_app("test")
    return app, app.test_client()


@_PROPERTY_SETTINGS
@given(password=_password_strategy)
def test_access_token_exp_minus_iat_equals_configured_ttl(password):
    app, client = _fresh_app_and_client()

    response = client.post(
        "/api/v1/auth/register",
        json={"email": "prop@example.com", "password": password},
    )
    assert response.status_code == 201
    access = response.get_json()["access"]

    with app.app_context():
        claims = decode_token(access, expected_type="access")
        expected_ttl = int(app.config["ACCESS_TTL_SECONDS"])
    assert claims["exp"] - claims["iat"] == expected_ttl


@_PROPERTY_SETTINGS
@given(password=_password_strategy)
def test_access_token_issued_in_past_rejects_on_me(password):
    """An access token whose exp is already in the past returns 401 TOKEN_EXPIRED on /me."""
    app, client = _fresh_app_and_client()

    register = client.post(
        "/api/v1/auth/register",
        json={"email": "prop@example.com", "password": password},
    )
    assert register.status_code == 201
    user_id = register.get_json()["user"]["id"]

    with app.app_context():
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        expired = encode_access_token(user_id, now=past)

    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"}
    )
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "TOKEN_EXPIRED"
