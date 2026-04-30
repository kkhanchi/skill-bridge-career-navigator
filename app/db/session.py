"""Request-scoped session plumbing.

Phase 2 session lifecycle:

1. ``init_extensions`` builds a :class:`sessionmaker` bound to the
   engine (``expire_on_commit=False``) and calls
   :func:`set_session_factory` to install it as a module global.
2. The ``before_request`` hook (registered in :mod:`app.__init__`)
   calls ``SessionLocal()`` and stashes the resulting :class:`Session`
   on ``flask.g.db_session``.
3. Repository methods read the session via :func:`get_db_session`.
4. The ``teardown_request`` hook commits on success, rolls back on
   exception, and always closes.

On the memory backend none of this runs — :func:`get_db_session`
raises loudly if a repository accidentally tries to reach for a
session it doesn't have, which catches misconfigured tests.

Design reference: `.kiro/specs/phase-2-persistence/design.md` §db/session.py.
Requirement reference: R4.1, R4.5, R4.6.
"""

from __future__ import annotations

from flask import g, has_request_context
from sqlalchemy.orm import Session, sessionmaker


# Installed at ``init_extensions`` time when the SQL backend is
# selected. Remains ``None`` on memory-backed apps — any call to
# ``get_db_session`` on such an app hits the guard below.
SessionLocal: sessionmaker[Session] | None = None


def set_session_factory(factory: sessionmaker[Session] | None) -> None:
    """Install (or clear) the module-level :class:`sessionmaker`.

    Called by :func:`app.extensions.init_extensions`. Passing ``None``
    clears the factory, which matters when a test rebuilds an app with
    a memory backend after one with a SQL backend.
    """
    global SessionLocal
    SessionLocal = factory


def get_db_session() -> Session:
    """Return the current request's :class:`Session`.

    Raises:
        RuntimeError: If called outside a Flask request context OR
            when no SQL backend is bound. Both are programming
            errors, not runtime conditions — fail loudly so the
            developer fixes the misconfiguration instead of silently
            using a ``None`` session.
    """
    if not has_request_context():
        raise RuntimeError(
            "get_db_session() called outside a Flask request context"
        )
    session = getattr(g, "db_session", None)
    if session is None:
        raise RuntimeError(
            "No DB session bound on flask.g — memory backend in use or "
            "request hooks not installed"
        )
    return session
