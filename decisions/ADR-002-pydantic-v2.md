# ADR-002: Pydantic v2 over Marshmallow / flask-smorest

- **Status:** Accepted
- **Date:** 2026-04-30
- **Phase:** 1 — REST API Foundation

## Context

The `plan.md` Phase 1 brief allowed either Pydantic v2 or Marshmallow
for request/response validation. Adjacent options also exist:

- **flask-smorest** — builds on Marshmallow, generates OpenAPI docs.
- **flask-pydantic** — thin wrapper that decorates handlers.
- **Bare Pydantic v2** — use `BaseModel.model_validate` inside
  hand-written decorators.

The API surface has twelve endpoints with straightforward boundary
validation (length caps, int ranges, `extra="forbid"`). We don't need
OpenAPI doc generation in Phase 1 (`plan.md` defers that to Phase 5).
We do need consistent error shape and a single seam for surfacing
validation errors as `VALIDATION_FAILED` with the Pydantic error list
embedded in `error.details.errors`.

## Decision

Use **bare Pydantic v2** with two local decorators in
`app/utils/validation.py`:

```python
@validate_body(ProfileCreate)
def handler(*, body: ProfileCreate): ...

@validate_query(JobListQuery)
def handler(*, query: JobListQuery): ...
```

Both decorators parse the raw input through the model and raise
`ApiError("VALIDATION_FAILED", ...)` on failure with
`errors(include_url=False, include_context=False)` — the latter flag
is essential because Pydantic's `ctx` dict can contain non-JSON
objects (e.g. the raw `ValueError` from a custom `model_validator`).

## Consequences

**Easier:**

- Typing: handlers declare `body: ProfileCreate` and get a concrete
  typed object, not a dict.
- Error shape: a single place (`_raise_validation_error`) controls
  how schema failures surface. Changes to the error contract land in
  one file, not 12.
- Performance: Pydantic v2 is Rust-core and fast enough that
  validation never shows up in profiles.

**Harder:**

- OpenAPI in Phase 5: we'll build it from `TypeAdapter`
  introspection rather than inheriting flask-smorest's generator.
  That's a known cost paid later.
- No automatic form-encoded body support. Phase 1 is JSON-only
  everywhere; if future phases need form bodies, we add a sibling
  decorator.

**Constrained:**

- `@validate_body` and `@validate_query` inject parsed models as
  keyword-only arguments (`body=` / `query=`). Handlers must use `*,`
  in their signature. This is a deliberate constraint — it makes the
  parsed payload visually distinct from URL path parameters.

## Rejected alternatives

- **Marshmallow**: more boilerplate for simple schemas; dual-library
  typing ecosystem (typing stubs lag).
- **flask-smorest**: bundles OpenAPI which we don't need yet, and
  locks us into its decorator style.
- **flask-pydantic**: fewer than 20 lines of code to write our own
  decorators; avoid the dependency.
