# ADR-008: Alembic workflow + env.py design

- **Status:** Accepted
- **Date:** 2026-04-30
- **Phase:** 2 — Persistence

## Context

Phase 2 needed a migration strategy. Three practical options:

1. **Alembic direct** — write `alembic.ini`, an `env.py` that
   imports our `DeclarativeBase.metadata`, check migrations into
   the repo.
2. **flask-migrate** — a thin wrapper around Alembic that hooks
   into Flask. Adds a CLI (`flask db upgrade`) but couples the
   migration story to Flask.
3. **Schema-on-startup via `Base.metadata.create_all`** — skip
   migrations, run `create_all` at app boot. Works for tests; no
   migration history, breaks the moment the schema changes in
   prod.

## Decision

Alembic direct.

- `alembic.ini` at `skill-bridge/alembic.ini` with
  `script_location = migrations`. `sqlalchemy.url` is **not** set
  here — the file stays credential-free and versionable.
- `migrations/env.py` pulls `DATABASE_URL` from
  `CONFIG_MAP[APP_ENV].DATABASE_URL` at runtime. One source of
  truth for connection strings; admins run migrations with the
  same env they'd run the app with.
- First migration (`0001_initial_schema.py`) is hand-curated
  from `alembic revision --autogenerate` output. Autogenerate gets
  ~90% right; the remaining 10% is mostly missing imports
  (autogenerate emitted `postgresql.JSONB(astext_type=Text())`
  without importing `Text`) and filename convention.
- CI gate: `alembic upgrade head` + `alembic downgrade base` +
  `alembic upgrade head` on a scratch SQLite file is a property
  test (R1.6 → `tests/integration/test_alembic_smoke.py`).

## Consequences

**Easier:**

- No new dependency on flask-migrate — one less wrapper in the
  stack to learn and debug.
- Migrations run in CI against SQLite without needing Postgres.
  The schema-round-trip property catches most divergence.
- Standard Alembic docs apply as-is; no custom CLI layer to
  explain in the README.

**Harder:**

- Contributors need to remember the `APP_ENV=dev` / `DATABASE_URL=...`
  env before running `alembic` commands. Documented in
  `migrations/README` and the main `README.md`.
- Autogenerate against SQLite won't emit `JSONB` — it emits
  plain `JSON`. For JSON-column changes, run autogenerate
  against a scratch Postgres before committing migrations.
  Trade-off accepted; noted in ADR-010 (JSONB portability).

**Constrained:**

- Every schema edit in `app/db/models.py` requires a new
  migration file. Autogenerate handles most, but index renames
  and variant-type tweaks need hand review. This is a feature,
  not a bug — it forces explicit consideration of migration
  semantics.
