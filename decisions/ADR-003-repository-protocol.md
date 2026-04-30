# ADR-003: In-memory repository abstraction behind a Protocol

- **Status:** Accepted
- **Date:** 2026-04-30
- **Phase:** 1 — REST API Foundation

## Context

Phase 1 explicitly has no database. The simplest implementation of
"store a profile" is a module-level dict, reached directly from
handlers. Phase 2 will introduce SQLAlchemy + Alembic and replace
in-memory storage with Postgres.

Two questions collide:

1. Do we introduce a repository abstraction in Phase 1, or write
   handlers that touch dicts directly and refactor later?
2. If we do add an abstraction, what shape — abstract base class,
   `Protocol`, or interface-by-convention?

Pros of introducing the seam now: Phase 2 becomes a mechanical
class-swap rather than a cross-cutting refactor. Cons: risk of
over-engineering for an in-memory store that fits on one page.

## Decision

Define **`typing.Protocol`-based repository interfaces** in
`app/repositories/base.py` — one Protocol per aggregate root
(`ProfileRepository`, `JobRepository`, `AnalysisRepository`,
`RoadmapRepository`) — and wire handlers exclusively through those
Protocols. Phase 1 ships in-memory `InMemory*Repository` classes that
conform structurally.

Identity is attached via `*Record` dataclass wrappers
(`ProfileRecord`, `JobRecord`, `AnalysisRecord`, `RoadmapRecord`) so
the existing `app.core.models` dataclasses stay framework-agnostic.
`RoadmapRecord` carries a `resource_index: dict[str, tuple[int, int]]`
for O(1) resource lookup during `PATCH /roadmaps/{id}/resources/{rid}`.

## Consequences

**Easier:**

- Phase 2 swap: introduce `SqlAlchemyProfileRepository` and the
  handlers don't move a line. Verified by construction — handlers
  import from `app.repositories.base`, never from `*_repo.py`
  implementations.
- Test isolation: `create_app("test")` instantiates fresh in-memory
  repos per test. No "reset the module global" incantation.
- Small cost today: the four in-memory impls fit in ~40 lines each.

**Harder:**

- Two types to reason about per resource (`UserProfile` the domain
  object, `ProfileRecord` the stored wrapper). Handlers have to
  remember to serialize from the record, not the domain object.

**Constrained:**

- `update_resource(roadmap_id, resource_id, completed) -> RoadmapRecord | None`
  returns `None` in **two** failure modes: missing roadmap OR missing
  resource within an existing roadmap. The handler disambiguates by
  calling `get(roadmap_id)` afterwards. Alternatives (custom exception
  types, two separate methods) would add more ceremony than this
  costs; documented in the repo module.
- In-memory repos are per-process. Gunicorn must run with `-w 1`
  during Phase 1 (documented in `wsgi.py`). Multi-worker correctness
  arrives with Phase 2 via the database.
