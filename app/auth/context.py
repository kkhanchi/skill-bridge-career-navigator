"""Thin context helper for the Phase 3 authenticated user.

The primary way handlers receive the current user is via the
``current_user`` kwarg injected by :func:`app.auth.decorator.require_auth`.
``get_current_user`` is a secondary read path for code that runs
outside the handler signature (logging, future middleware) but inside
the same request.

Design reference: `.kiro/specs/phase-3-auth/design.md` §context.py.
Requirement reference: R13.7.
"""

from __future__ import annotations

from flask import g

from app.repositories.base import UserRecord


def get_current_user() -> UserRecord:
    """Return the authenticated user for the current request.

    Raises:
        RuntimeError: If called before ``@require_auth`` has populated
            ``g.current_user``. That's a programmer error (forgot the
            decorator), not a runtime condition; fail loudly.
    """
    user = getattr(g, "current_user", None)
    if user is None:
        raise RuntimeError(
            "get_current_user() called before @require_auth populated g"
        )
    return user
