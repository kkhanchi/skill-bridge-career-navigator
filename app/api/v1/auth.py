"""Authentication endpoints under ``/api/v1/auth``.

Five handlers:

  - POST /register  — create user + issue tokens (201)
  - POST /login     — verify credentials + issue tokens (200)
  - POST /refresh   — rotate refresh token, issue new pair (200)
  - POST /logout    — revoke refresh (204, idempotent)
  - GET  /me        — introspect current user (200)

Rate limits (R13.2) are attached with ``@limiter.limit(...)`` per-route;
the decorator runs BEFORE ``@validate_body`` so 31st request returns
429 RATE_LIMITED before Pydantic even looks at the body. Bypassing
body validation on rate-limited requests is intentional.

Design reference: `.kiro/specs/phase-3-auth/design.md` §Endpoints.
Requirement reference: R1, R2, R3, R4, R5, R13.2.
"""

from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify

from app.auth.decorator import require_auth
from app.auth.tokens import AuthError, decode_token, encode_access_token, encode_refresh_token
from app.extensions import get_ext
from app.repositories.base import UserRecord
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    MeResponse,
    RefreshPairResponse,
    RefreshRequest,
    RegisterRequest,
    TokenPairResponse,
    UserResponse,
)
from app.utils.errors import (
    AUTH_REQUIRED,
    EMAIL_TAKEN,
    INVALID_CREDENTIALS,
    TOKEN_INVALID,
    ApiError,
)
from app.utils.validation import validate_body

logger = logging.getLogger(__name__)

bp = Blueprint("auth", __name__)


# ---------------------------------------------------------------------------
# Lazy per-app limit decorators
# ---------------------------------------------------------------------------
#
# flask-limiter lives on Extensions (per-app). Handlers are declared
# at module import time before any app exists, so we can't attach
# ``@limiter.limit("5/hour")`` directly. Instead, a small wrapper
# defers lookup to request time and applies the current app's limiter
# dynamically — same observable behaviour, just indirected.


def _with_limit(limit_str: str):
    """Return a decorator that applies ``limiter.limit(limit_str)`` at request time."""

    def decorator(fn):
        from functools import wraps

        @wraps(fn)
        def wrapper(*args, **kwargs):
            limiter = get_ext().limiter
            if limiter is None:
                # No limiter wired — behave as if the limit didn't exist.
                # This path is only hit on a misconfigured test app.
                return fn(*args, **kwargs)
            limited = limiter.limit(limit_str)(fn)
            return limited(*args, **kwargs)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def _serialize_user(user: UserRecord) -> dict:
    return UserResponse(
        id=user.id,
        email=user.email,
        created_at=user.created_at,
    ).model_dump(mode="json")


# ---------------------------------------------------------------------------
# Shared post-auth helper: mint both tokens + persist the refresh.
# ---------------------------------------------------------------------------


def _issue_tokens(user: UserRecord) -> tuple[str, str]:
    """Mint an access + refresh pair and persist the refresh's jti row.

    Persistence happens BEFORE returning the token to the caller so
    the refresh_tokens row is guaranteed present by the time the
    client could ever present the token (R3.6: token validity
    requires a row).
    """
    ext = get_ext()
    access = encode_access_token(user.id)
    refresh, jti, expires_at = encode_refresh_token(user.id)
    ext.refresh_token_repo.create(
        user_id=user.id, jti=jti, expires_at=expires_at,
    )
    return access, refresh


# ---------------------------------------------------------------------------
# POST /register
# ---------------------------------------------------------------------------


@bp.post("/register")
@_with_limit("5/hour")
@validate_body(RegisterRequest)
def register_handler(*, body: RegisterRequest):
    """Create a new account and return an initial token pair."""
    ext = get_ext()

    # Uniqueness check before insert. The SQL backend's UNIQUE
    # constraint on users.email is the final safety net if two
    # requests race past this check.
    if ext.user_repo.exists_by_email(body.email):
        raise ApiError(EMAIL_TAKEN, "Email already registered", status=409)

    password_hash = ext.hasher.hash(body.password)
    user = ext.user_repo.create(email=body.email, password_hash=password_hash)

    access, refresh = _issue_tokens(user)
    response = TokenPairResponse(
        user=UserResponse(id=user.id, email=user.email, created_at=user.created_at),
        access=access,
        refresh=refresh,
    )
    return jsonify(response.model_dump(mode="json")), 201


# ---------------------------------------------------------------------------
# POST /login
# ---------------------------------------------------------------------------


@bp.post("/login")
@_with_limit("10/minute")
@validate_body(LoginRequest)
def login_handler(*, body: LoginRequest):
    """Authenticate a user and return an access + refresh pair.

    Constant-time verify on the unknown-email branch closes the
    account-enumeration timing side channel (R2.4). ``verify`` is
    called against the hasher's pre-computed ``dummy_hash`` with
    the attempted password so the total CPU time for "user missing"
    and "wrong password" is effectively identical.
    """
    ext = get_ext()
    user = ext.user_repo.get_by_email(body.email)

    if user is None:
        # Constant-time comparison: run verify against the dummy so
        # the response timing matches a real failed-password path.
        # The return value is discarded — we already know the outcome.
        ext.hasher.verify(ext.hasher.dummy_hash, body.password)
        raise ApiError(
            INVALID_CREDENTIALS, "Invalid email or password", status=401
        )

    if not ext.hasher.verify(user.password_hash, body.password):
        raise ApiError(
            INVALID_CREDENTIALS, "Invalid email or password", status=401
        )

    access, refresh = _issue_tokens(user)
    response = TokenPairResponse(
        user=UserResponse(id=user.id, email=user.email, created_at=user.created_at),
        access=access,
        refresh=refresh,
    )
    return jsonify(response.model_dump(mode="json")), 200


# ---------------------------------------------------------------------------
# POST /refresh
# ---------------------------------------------------------------------------


@bp.post("/refresh")
@_with_limit("30/minute")
@validate_body(RefreshRequest)
def refresh_handler(*, body: RefreshRequest):
    """Rotate the refresh token: revoke the presented one, mint a new pair."""
    ext = get_ext()

    try:
        claims = decode_token(body.refresh, expected_type="refresh")
    except AuthError as err:
        raise ApiError(err.code, err.message, status=401) from err

    jti = claims["jti"]
    row = ext.refresh_token_repo.get_by_jti(jti)
    # Reuse of a revoked jti or an unknown jti both surface as
    # TOKEN_INVALID — no reason to distinguish them to the caller
    # (design Open Question Q3).
    if row is None or row.revoked_at is not None:
        raise ApiError(TOKEN_INVALID, "Refresh token is not valid", status=401)

    # Rotation: revoke the presented token, then mint + persist a new
    # one. Order matters — if persistence of the new one fails, the
    # old token is already revoked, forcing a fresh login. That's
    # safer than ever handing out two live tokens to the same jti.
    ext.refresh_token_repo.revoke(jti)

    user = ext.user_repo.get_by_id(row.user_id)
    if user is None:
        # Token is valid but the owning user was deleted. Same 401
        # surface as the @require_auth path.
        raise ApiError(TOKEN_INVALID, "Refresh token is not valid", status=401)

    access, refresh = _issue_tokens(user)
    response = RefreshPairResponse(access=access, refresh=refresh)
    return jsonify(response.model_dump(mode="json")), 200


# ---------------------------------------------------------------------------
# POST /logout
# ---------------------------------------------------------------------------


@bp.post("/logout")
@validate_body(LogoutRequest)
def logout_handler(*, body: LogoutRequest):
    """Revoke the presented refresh token. Always 204 (idempotent).

    Logout never returns a 4xx beyond a malformed body (missing
    ``refresh`` field, already caught by Pydantic as VALIDATION_FAILED).
    A malformed or already-revoked token still produces 204 — defensive
    UX for a user clicking "log out" twice.
    """
    ext = get_ext()
    try:
        claims = decode_token(body.refresh, expected_type="refresh")
    except AuthError:
        # Bad token -> best-effort revoke is impossible, but we still
        # return 204 so the client's "logged out" state is consistent.
        return "", 204

    # ``revoke`` is idempotent — returns False for unknown-or-already-revoked
    # but doesn't raise. We don't inspect the return value because the
    # 204 is unconditional.
    ext.refresh_token_repo.revoke(claims["jti"])
    return "", 204


# ---------------------------------------------------------------------------
# GET /me
# ---------------------------------------------------------------------------


@bp.get("/me")
@require_auth
def me_handler(*, current_user: UserRecord):
    """Return the authenticated user's public projection."""
    response = MeResponse(
        user=UserResponse(
            id=current_user.id,
            email=current_user.email,
            created_at=current_user.created_at,
        )
    )
    return jsonify(response.model_dump(mode="json")), 200
