"""The ``@require_auth`` view decorator (Phase 3).

Wraps a handler so it:

1. Reads the ``Authorization`` header; missing or not starting with
   the exact string ``"Bearer "`` raises ``ApiError(AUTH_REQUIRED, 401)``.
2. Extracts the bearer token; an empty token also raises ``AUTH_REQUIRED``.
3. Calls :func:`tokens.decode_token` with ``expected_type="access"``,
   translating any ``AuthError`` into an ``ApiError`` that carries the
   same 401 code (``TOKEN_EXPIRED`` or ``TOKEN_INVALID``).
4. Resolves the ``sub`` claim through ``ext.user_repo.get_by_id``; if
   no such user exists (deleted mid-token-lifetime), raises
   ``ApiError(TOKEN_INVALID, 401)``.
5. Stashes the resolved :class:`UserRecord` on ``flask.g.current_user``
   AND injects it as a ``current_user`` kwarg into the wrapped handler.

The decorator runs INSIDE the matched view function (not a global
``before_request`` hook) so only routes that explicitly opt in are
protected — public routes like ``/health`` and ``/jobs`` stay open.

Design reference: `.kiro/specs/phase-3-auth/design.md` §@require_auth.
Requirement reference: R5.2, R5.3, R5.4, R13.7, R13.8.
"""

from __future__ import annotations

from functools import wraps

from flask import g, request

from app.auth.tokens import AuthError, decode_token
from app.extensions import get_ext
from app.utils.errors import (
    AUTH_REQUIRED,
    TOKEN_INVALID,
    ApiError,
)


_BEARER_PREFIX = "Bearer "


def require_auth(fn):
    """Require a valid access token on the wrapped handler.

    On success, the handler receives a ``current_user`` keyword
    argument carrying a :class:`app.repositories.base.UserRecord`.
    On any failure, raises :class:`ApiError` with one of three
    Phase 3 codes (all 401): ``AUTH_REQUIRED``, ``TOKEN_EXPIRED``,
    or ``TOKEN_INVALID``.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header or not header.startswith(_BEARER_PREFIX):
            # Missing or malformed header. Per the design matrix this
            # is always AUTH_REQUIRED, not TOKEN_INVALID — we haven't
            # even looked at a token yet.
            raise ApiError(
                AUTH_REQUIRED,
                "Missing or invalid Authorization header",
                status=401,
            )

        token = header[len(_BEARER_PREFIX) :].strip()
        if not token:
            raise ApiError(
                AUTH_REQUIRED,
                "Missing bearer token",
                status=401,
            )

        try:
            claims = decode_token(token, expected_type="access")
        except AuthError as err:
            # AuthError carries a code that's already one of the two
            # valid 401 codes (TOKEN_EXPIRED / TOKEN_INVALID). Just
            # re-wrap it into the HTTP-level ApiError.
            raise ApiError(err.code, err.message, status=401) from err

        user = get_ext().user_repo.get_by_id(claims["sub"])
        if user is None:
            # Token is cryptographically valid but the referenced
            # user was deleted mid-token-lifetime. Surface as
            # TOKEN_INVALID — the client should log in again.
            raise ApiError(
                TOKEN_INVALID,
                "Token refers to an unknown user",
                status=401,
            )

        # Both sinks: g for code that reads from context (logging,
        # future middleware) and kwarg for the handler's signature.
        g.current_user = user
        kwargs["current_user"] = user
        return fn(*args, **kwargs)

    return wrapper
