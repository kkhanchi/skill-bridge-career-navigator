# ADR-007: Dual-backend repositories (memory + SQLAlchemy)

- **Status:** Accepted
- **Date:** 2026-04-30
- **Phase:** 2 — Persistence

## Context

Phase 1 (ADR-003) shipped `typing.Protocol`-based repository
interfaces with in-memory dict implementations. Phase 2's job was to
land SQLAlchemy. Two ways to do that:

1. **Replace** — delete `InMemory*Repository`, point everything at
   `SqlAlchemy*Repository`. Cleaner at the file level. But:
   - The 89 Phase 1 tests would all need a DB fixture, making
     `pytest` slower.
   - The equivalence hypothesis couldn't be tested directly —
     there's nothing to compare against.
   - Any regression in the SQL implementation would have no
     "baseline" to catch drift.

2. **Keep both** — add `SqlAlchemy*Repository` alongside the
   in-memory classes, select between them at `init_extensions` time
   via `DATABASE_URL` / `REPO_BACKEND`.

## Decision

Keep both. `TestConfig` forces `REPO_BACKEND="memory"` so the 89
Phase 1 tests continue running against the in-memory backend
unchanged. A new `TestSqlConfig` binds `sqlite:///:memory:` for a
set of SQL-specific integration tests. Dev defaults to SQLite;
Prod reads `DATABASE_URL` from env.

The verification story is a Hypothesis `RuleBasedStateMachine`
(`tests/properties/test_repository_equivalence.py`) that drives
both backends through the same random operation sequence and
asserts observable equivalence after every step.

## Consequences

**Easier:**

- Zero test regression from Phase 1 — all 89 original tests
  continue to pass unmodified against their original backend.
- The Protocol seam actually earns its keep: we can say
  "handlers don't know which backend they're talking to" and
  point at a property test that proves it.
- Benchmarking is trivial: flip `REPO_BACKEND=memory` on any
  config and you're running in-memory without touching a
  single line of handler code.
- Local dev works offline — no Postgres required; SQLite file
  in the working directory is the default.

**Harder:**

- Two classes per repo type instead of one. Six files instead
  of four. Minor.
- A handler bug that only manifests on SQL would need an
  integration test against the SQL backend to catch. The
  equivalence property test mitigates this — any behavioral
  divergence is a Hypothesis failure.

**Constrained:**

- Every new repository method has to land in both impl classes
  before it can be merged. The Protocol definition is the
  source of truth; either side failing to implement a new
  method is a type error immediately.
- The equivalence property will fail loudly if anyone adds a
  method that behaves differently between backends, which is a
  good thing but constrains the design space (no
  memory-only optimizations without a fallback path).

## Implementation notes

Two real bugs surfaced during property-test development that would
have been easy to ship:

1. Building `TestSqlConfig` with a hand-crafted `backend-developer`
   row missing `PostgreSQL` from preferred_skills — the property
   test immediately diverged on gap analysis. Fix: use `seed_db`
   to populate the SQL app from the same `data/jobs.json` the
   memory app loads.

2. `psycopg[binary]` (our Postgres driver) is `psycopg` 3.x, but
   SQLAlchemy defaults a bare `postgresql://...` URL to `psycopg2`.
   `build_engine` now rewrites bare URLs to `postgresql+psycopg://`
   so prod users don't hit `ModuleNotFoundError` on boot.
