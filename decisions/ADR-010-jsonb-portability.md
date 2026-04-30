# ADR-010: JSONB portability via SQLAlchemy variants

- **Status:** Accepted
- **Date:** 2026-04-30
- **Phase:** 2 — Persistence

## Context

Profiles, jobs, analyses, and roadmaps all store semi-structured
data (skill lists, categorization groups, phases). Two DB dialects
to support:

- **SQLite** — stores JSON as TEXT with a `JSON` affinity; no
  native type.
- **Postgres** — has native `JSONB` with indexing and operator
  support.

Options:

1. **Split model definitions per dialect** — `models_sqlite.py` +
   `models_postgres.py`. Accurate but doubles the surface area,
   forks the domain layer, and splits autogenerate.
2. **Portable JSON type via `with_variant`** — one column
   definition emits `JSON` on SQLite and `JSONB` on Postgres.
   Same model file, same ORM code, same mapper.
3. **Always use plain `JSON`** — Postgres would just store text
   too. Gives up native JSONB operators and indexing forever.

## Decision

Portable JSON type. Every JSON-bearing column declares:

```python
_JSONB = JSON().with_variant(JSONB(), "postgresql")
```

in `app/db/models.py`. Repositories never inspect the dialect —
they deal in Python `list[str]` / `dict` values and SQLAlchemy
handles the serialization.

Nested JSON mutations require a `flag_modified(row, "column")`
call because SQLAlchemy only tracks column-level assignments, not
nested dict/list mutations. The `SqlAlchemyRoadmapRepository.
update_resource` method is the one place this matters; it's
covered by `R7.1` + the `flag_modified` persistence integration
test.

## Consequences

**Easier:**

- One set of ORM models for two backends. Mapper code, repo
  code, test code — all share the same type signatures.
- Property tests (R7.4 JSONB round-trip) run on SQLite in CI but
  structurally validate the same serialization path Postgres
  would use.

**Harder:**

- `alembic revision --autogenerate` against SQLite won't emit
  `JSONB` instructions for JSON-column changes. For JSON-column
  schema edits, run autogenerate against a scratch Postgres
  (`docker run -p 5432:5432 postgres:15`). Documented in the
  spec's design Open Question 7.
- In-place JSON mutations silently no-op without `flag_modified`.
  This is a real footgun — `R7.1` + the persistence integration
  test + the `R7.3` property test all exist to catch it. Any
  future method that mutates JSON in place needs to call
  `flag_modified` by convention.

**Constrained:**

- Postgres-specific features like GIN indexes on JSONB, JSON
  path operators (`@>`, `?`), and JSON-containment queries are
  not used in Phase 2. Revisit in Phase 5 if deployment pressure
  argues for it — the column type doesn't need to change, only
  the queries.
- JSON-stored lists are read and written as opaque blobs — no
  per-element constraints, no validation at the DB layer.
  Pydantic covers this at the API boundary.
