"""JWT encode/decode primitives for access and refresh tokens (Phase 3).

HS256-signed JWTs with a `type` claim that distinguishes access from
refresh tokens so neither can be substituted for the other at the
decoder. The only external surface out of this module is:

- `AuthError` — a single exception type carrying a machine code
  (`TOKEN_EXPIRED` or `TOKEN_INVALID`) and a human-readable message.
  All PyJWT-internal exceptions collapse into this one type inside
  `decode_token` so no PyJWT class leaks past the auth layer (R8.6).

- `encode_access_token(user_id)` -> str
- `encode_refresh_token(user_id)` -> (token, jti, expires_at)
- `decode_token(token, *, expected_type)` -> dict of claims

Both encoders accept an optional `now` parameter as a
dependency-injection seam for tests — production callers let it
default to `datetime.now(timezone.utc)`.

Design reference: `.kiro/specs/phase-3-auth/design.md` §Signing and
secret management / §encode_access_token / §decode_token.
Requirement reference: R8.1, R8.2, R8.3, R8.6, R8.7.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import jwt
from flask import current_app


_ACCESS = "access"
_REFRESH = "refresh"
_ALGORITHM = "HS256"


class AuthError(Exception):
    """Decoder failure that must be mapped to a specific 401 error code.

    The `code` is one of the two `app.utils.errors` constants that the
    `@require_auth` decorator and the `/auth/refresh` handler convert
    into the Error_Envelope response:

    - `"TOKEN_EXPIRED"` — the signature verifies but `exp` is in the
      past. Surfaced as 401 with the same code in the body.
    - `"TOKEN_INVALID"` — every other decoder failure: bad signature,
      malformed token, wrong `type` claim, missing required claim,
      or a hash that PyJWT cannot parse at all.

    Callers MUST NOT construct `AuthError` with any other code — the
    decorator's error-to-HTTP mapping table only knows these two.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_utc(now: Optional[datetime]) -> datetime:
    """Resolve the effective "now" timestamp.

    Tests pass a frozen datetime to exercise expiry boundaries
    deterministically. Production callers pass None and take the
    real wall clock. We always work in UTC — mixing naive and aware
    datetimes silently breaks `exp` arithmetic.
    """
    return now if now is not None else datetime.now(timezone.utc)


def _secret() -> str:
    """Fetch the JWT signing secret from the active Flask config.

    A missing or empty `JWT_SECRET` is a boot-time configuration
    error — `Extensions.init` raises before any request reaches this
    code on prod. In tests and dev the config provides a literal
    default, so this read is safe at request time.
    """
    return current_app.config["JWT_SECRET"]


# ---------------------------------------------------------------------------
# Encoders
# ---------------------------------------------------------------------------


def encode_access_token(
    user_id: str,
    *,
    now: Optional[datetime] = None,
) -> str:
    """Return an HS256 JWT with `type="access"` and a 15-minute expiry.

    Claims: `sub`, `iat`, `exp = iat + ACCESS_TTL_SECONDS`, `jti`
    (fresh uuid4 hex), `type="access"`. `jti` is not persisted for
    access tokens — it exists for log correlation and future denylist
    support.
    """
    issued_at = _now_utc(now)
    ttl_seconds = int(current_app.config["ACCESS_TTL_SECONDS"])
    expires_at = issued_at + _timedelta_seconds(ttl_seconds)
    claims = {
        "sub": user_id,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": uuid4().hex,
        "type": _ACCESS,
    }
    return jwt.encode(claims, _secret(), algorithm=_ALGORITHM)


def encode_refresh_token(
    user_id: str,
    *,
    now: Optional[datetime] = None,
) -> tuple[str, str, datetime]:
    """Return `(token, jti, expires_at)` for a refresh JWT.

    The caller (login/register handler) MUST persist `(jti,
    expires_at)` in the `refresh_tokens` table BEFORE returning the
    token to the client. If the insert fails, we must not hand out a
    token whose `jti` has no row — the rotation-on-refresh flow would
    reject it as revoked-or-unknown, but the client would still carry
    a signed token it cannot use.
    """
    issued_at = _now_utc(now)
    ttl_seconds = int(current_app.config["REFRESH_TTL_SECONDS"])
    expires_at = issued_at + _timedelta_seconds(ttl_seconds)
    jti = uuid4().hex
    claims = {
        "sub": user_id,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": jti,
        "type": _REFRESH,
    }
    token = jwt.encode(claims, _secret(), algorithm=_ALGORITHM)
    return token, jti, expires_at


# ---------------------------------------------------------------------------
# Decoder
# ---------------------------------------------------------------------------


def decode_token(token: str, *, expected_type: str) -> dict:
    """Decode and verify a JWT, asserting `type == expected_type`.

    Success path returns the full claims dict with at minimum
    `{sub, iat, exp, jti, type}`.

    All failure paths raise `AuthError`:

    - PyJWT `ExpiredSignatureError` -> `AuthError(TOKEN_EXPIRED)`.
    - Every other `jwt.InvalidTokenError` subclass (bad signature,
      malformed, missing-required-claim-per-PyJWT) -> `TOKEN_INVALID`.
    - The token decodes but `claims["type"] != expected_type` ->
      `TOKEN_INVALID`. This is what stops a refresh token from being
      accepted as an access token on a protected route.
    - The token decodes but lacks `sub` or `jti` -> `TOKEN_INVALID`.
      PyJWT only enforces presence of claims we explicitly register,
      so we assert these manually. `type` presence is already covered
      by the equality check above.
    """
    try:
        claims = jwt.decode(token, _secret(), algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("TOKEN_EXPIRED", "Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        # Covers InvalidSignatureError, DecodeError, InvalidAlgorithmError,
        # ImmatureSignatureError, etc. All collapse to TOKEN_INVALID.
        raise AuthError("TOKEN_INVALID", "Token is invalid") from exc

    if claims.get("type") != expected_type:
        raise AuthError(
            "TOKEN_INVALID",
            f"Expected token type {expected_type!r}",
        )
    if "sub" not in claims or "jti" not in claims:
        raise AuthError("TOKEN_INVALID", "Token is missing required claims")

    return claims


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


def _timedelta_seconds(seconds: int):
    """Small helper keeping the top-of-file import list tidy.

    `datetime.timedelta` is the only piece of `datetime` we use
    arithmetically and only in the two encoders. Centralising it here
    makes the call sites read as plain `issued_at + delta`.
    """
    from datetime import timedelta

    return timedelta(seconds=seconds)
