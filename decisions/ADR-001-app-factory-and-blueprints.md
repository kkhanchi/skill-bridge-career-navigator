# ADR-001: App factory + blueprint-per-resource layout

- **Status:** Accepted
- **Date:** 2026-04-30
- **Phase:** 1 — REST API Foundation

## Context

Flask supports two common project layouts:

1. **Module-level app**: declare `app = Flask(__name__)` at module top
   level and register routes directly via `@app.route`. Simple to
   start, but you get exactly one app per process — test isolation
   requires ugly workarounds (reassigning state, monkeypatching
   extensions), and any configuration switch has to happen before
   import time.
2. **Application factory**: a `create_app(config_name)` function builds
   and returns a fresh `Flask` instance, configuring it for the
   requested environment. Each call produces an independent app with
   its own config, extensions, and state.

Orthogonal to that: how to organize routes. Options include
one-blueprint-per-verb (`read_bp`, `write_bp`), one-blueprint-per-resource
(`profiles_bp`, `jobs_bp`), or just dumping everything into the factory.

## Decision

Adopt the **application factory** pattern. `create_app(config_name)`
in `app/__init__.py` is the single entry point used by `run.py`,
`wsgi.py`, and every test fixture.

Organize routes as **one blueprint per resource root**: profiles,
resume, jobs, analyses, roadmaps. Each blueprint owns the handlers
for its resource regardless of HTTP method. Cross-cutting concerns
(correlation id, logging, errors) live in request hooks and handlers
registered by the factory, not in individual blueprints.

## Consequences

**Easier:**

- Independent test apps. `create_app("test")` per test keeps
  in-memory repository state isolated without ceremony — verified by
  the profile round-trip and pagination partition property tests
  that each build a fresh client.
- Config switching. `TestConfig` forces the `FallbackCategorizer` and
  plain-text logs; `DevConfig` turns on debug-level JSON logs;
  `ProdConfig` is the gunicorn target. One `config_name` picks the
  whole bundle.
- Swapping extensions in later phases (SQLAlchemy in Phase 2, JWT
  middleware in Phase 3) is a change inside `create_app` — route
  code stays untouched.

**Harder:**

- Slightly more indirection than a module-level app. Anyone new to
  the codebase has to follow `create_app -> init_extensions ->
  get_ext()` to reach the repositories. This is the standard cost of
  the factory pattern; it's documented in `app/__init__.py`.

**Constrained:**

- Blueprints can't import the factory directly (circular imports);
  they read shared state via `get_ext()` which resolves through
  `current_app`. This is intentional — blueprints stay ignorant of
  the app assembly order.
