"""Unit tests for JWT encode/decode helpers.

All tests run inside a fresh `create_app("test")` app context because
both encoders and the decoder read `JWT_SECRET` and the TTL values
off `current_app.config`.

Requirement reference: R8.1, R8.2, R8.3, R8.6, R8.7.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis.strategies import text

from app.auth.tokens import (
    AuthError,
    decode_token,
    encode_access_token,
    encode_refresh_token,
)


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_access_token_round_trip_returns_expected_claims(app):
    with app.app_context():
        uid = uuid4().hex
        token = encode_access_token(uid)
        claims = decode_token(token, expected_type="access")
    assert claims["sub"] == uid
    assert claims["type"] == "access"
    assert claims["exp"] > claims["iat"]
    assert "jti" in claims


def test_refresh_token_round_trip_returns_expected_claims(app):
    with app.app_context():
        uid = uuid4().hex
        token, jti, expires_at = encode_refresh_token(uid)
        claims = decode_token(token, expected_type="refresh")
    assert claims["sub"] == uid
    assert claims["type"] == "refresh"
    # The jti returned alongside the token must equal the jti claim —
    # the caller relies on this to persist the row keyed by jti.
    assert claims["jti"] == jti
    # expires_at returned to the caller matches the exp claim.
    assert int(expires_at.timestamp()) == claims["exp"]


def test_access_token_exp_is_near_ttl_window(app):
    with app.app_context():
        ttl = app.config["ACCESS_TTL_SECONDS"]
        token = encode_access_token("uid-1")
        claims = decode_token(token, expected_type="access")
    # exp - iat MUST equal the configured TTL exactly — both ints.
    assert claims["exp"] - claims["iat"] == ttl


def test_refresh_token_exp_is_near_ttl_window(app):
    with app.app_context():
        ttl = app.config["REFRESH_TTL_SECONDS"]
        token, _, _ = encode_refresh_token("uid-1")
        claims = decode_token(token, expected_type="refresh")
    assert claims["exp"] - claims["iat"] == ttl


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------


def test_expired_access_token_raises_token_expired(app):
    with app.app_context():
        # Push "now" far enough into the past that exp < real wall-clock.
        in_the_past = datetime.now(timezone.utc) - timedelta(hours=2)
        token = encode_access_token("uid-1", now=in_the_past)
        with pytest.raises(AuthError) as ei:
            decode_token(token, expected_type="access")
    assert ei.value.code == "TOKEN_EXPIRED"


def test_expired_refresh_token_raises_token_expired(app):
    with app.app_context():
        in_the_past = datetime.now(timezone.utc) - timedelta(days=30)
        token, _, _ = encode_refresh_token("uid-1", now=in_the_past)
        with pytest.raises(AuthError) as ei:
            decode_token(token, expected_type="refresh")
    assert ei.value.code == "TOKEN_EXPIRED"


# ---------------------------------------------------------------------------
# Invalid tokens
# ---------------------------------------------------------------------------


def test_wrong_secret_raises_token_invalid(app):
    # Craft a token signed with a different secret. Its claims look
    # fine but the HS256 signature fails verification under our
    # JWT_SECRET.
    claims = {
        "sub": "uid-1",
        "iat": 0,
        "exp": 9_999_999_999,
        "jti": uuid4().hex,
        "type": "access",
    }
    forged = jwt.encode(claims, "some-other-secret", algorithm="HS256")
    with app.app_context():
        with pytest.raises(AuthError) as ei:
            decode_token(forged, expected_type="access")
    assert ei.value.code == "TOKEN_INVALID"


def test_malformed_token_string_raises_token_invalid(app):
    with app.app_context():
        with pytest.raises(AuthError) as ei:
            decode_token("not.a.jwt", expected_type="access")
    assert ei.value.code == "TOKEN_INVALID"


def test_refresh_token_rejected_when_expecting_access(app):
    # A perfectly valid refresh token MUST not decode as an access
    # token — this is the substitution defense (R8.3).
    with app.app_context():
        token, _, _ = encode_refresh_token("uid-1")
        with pytest.raises(AuthError) as ei:
            decode_token(token, expected_type="access")
    assert ei.value.code == "TOKEN_INVALID"


def test_access_token_rejected_when_expecting_refresh(app):
    with app.app_context():
        token = encode_access_token("uid-1")
        with pytest.raises(AuthError) as ei:
            decode_token(token, expected_type="refresh")
    assert ei.value.code == "TOKEN_INVALID"


def test_missing_sub_claim_raises_token_invalid(app):
    # Hand-craft a signed token with no `sub`. PyJWT happily encodes
    # any dict; the decoder must enforce the claim presence itself.
    with app.app_context():
        secret = app.config["JWT_SECRET"]
        claims = {
            "iat": 0,
            "exp": 9_999_999_999,
            "jti": uuid4().hex,
            "type": "access",
        }
        token = jwt.encode(claims, secret, algorithm="HS256")
        with pytest.raises(AuthError) as ei:
            decode_token(token, expected_type="access")
    assert ei.value.code == "TOKEN_INVALID"


def test_missing_jti_claim_raises_token_invalid(app):
    with app.app_context():
        secret = app.config["JWT_SECRET"]
        claims = {
            "sub": "uid-1",
            "iat": 0,
            "exp": 9_999_999_999,
            "type": "access",
        }
        token = jwt.encode(claims, secret, algorithm="HS256")
        with pytest.raises(AuthError) as ei:
            decode_token(token, expected_type="access")
    assert ei.value.code == "TOKEN_INVALID"


# ---------------------------------------------------------------------------
# Property test: encode/decode round-trip preserves subject and type (R8.7)
# ---------------------------------------------------------------------------

# Arbitrary non-empty printable-ish user ids. Realistically these will
# always be uuid hex, but the encoder makes no such assumption — it
# just stringifies whatever goes into `sub`. This keeps the property
# honest against future user-id changes.
_user_id_strategy = text(min_size=1, max_size=64).filter(lambda s: s.strip() != "")


@settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(user_id=_user_id_strategy)
def test_access_token_round_trip_property(app, user_id):
    """FOR ALL non-empty user_id, decode(encode(uid)).sub == uid."""
    with app.app_context():
        token = encode_access_token(user_id)
        claims = decode_token(token, expected_type="access")
    assert claims["sub"] == user_id
    assert claims["type"] == "access"
    assert claims["exp"] > claims["iat"]
