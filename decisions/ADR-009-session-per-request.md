# ADR-009: Session-per-request via before_request / teardown_request

- **Status:** Accepted
- **Date:** 2026-04-30
- **Phase:** 2 — Persistence

## Context

SQLAlchemy offers a few session lifecycle patterns:

1. **Scoped session** — `scoped_session(sessionmaker(...))` keyed
   by the current thread / greenlet. Works, but adds an extra
   abstraction and its scope isn't perfectly aligned with Flask's
   request cycle under every WSGI setup.
2. **Per-request session via Flask hooks** — open a fresh
   `Session()` in `before_request`, stash on `flask.g`, commit
   or rollback in `teardown_request`, always close.
3. **Handler-managed** — each handler opens and closes its own
   session. Maximum explicit control, but every handler has to
   remember the try/commit/except/rollback/finally/close dance.

## Decision

Session-per-request via Flask hooks.

- Phase 1 already stubbed `teardown_request` for this exact
  extension, so the hook scaffolding was free.
- `sessionmaker(..., expire_on_commit=False)` so handlers can
  read fields off returned `Record` objects after the
  teardown commit has fired (without `False`, every attribute
  access on a post-commit ORM row triggers a reload).
- `get_db_session()` accessor in `app/db/session.py` raises
  `RuntimeError` outside a request context or when no SQL
  backend is bound — catches repo misconfigurations loudly at
  test time.
- On the memory backend the hooks are no-ops — the session
  factory is `None`, `g.db_session` never gets set, teardown
  pops `None` and returns. Zero overhead for memory-only
  requests (R4.4).

## Consequences

**Easier:**

- Handlers stay free of transaction boilerplate. The session is
  already open when a handler runs; commit or rollback happens
  automatically based on whether an exception propagated.
- One clear rule for "when is my write durable?" — at the end
  of the request, in `teardown_request`. Works for both
  success and error paths.
- Mixing sync handlers with future Celery tasks (Bonus phase
  option B) would just mean tasks build their own session
  outside the request scope. The pattern composes.

**Harder:**

- Handlers that trigger a SQL error mid-request see a 500 with
  no specific error code. SQLAlchemy's `IntegrityError` bubbles
  up through the catch-all `Exception` handler (R6.4) →
  `INTERNAL_ERROR`. Phase 3 auth handlers will want specific
  mapping for `users.email` uniqueness violations; crossing
  that bridge later.

**Constrained:**

- Background jobs (Bonus phase B) can't share the
  request-scoped session. If we add Celery, each task builds
  its own `Session()` outside the request hook cycle.
- Multi-worker gunicorn is now safe once the SQL backend is
  active — every worker gets its own engine + session factory,
  all writing to the same shared DB. Phase 1's `-w 1`
  constraint is lifted (memory backend still needs `-w 1` of
  course).
