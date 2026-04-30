# ADR-014: Additive `*_for_user` extension over breaking signature change

- **Status:** Accepted
- **Date:** 2026-04-30
- **Phase:** 3 — Authentication

## Context

Phase 3 adds multi-tenant filtering to every profile/analysis/roadmap
handler. Two Protocol-evolution options:

1. **Breaking change** — modify every existing method signature to
   take a `user_id` parameter:
   ```python
   def get(self, profile_id: str, user_id: str) -> ProfileRecord | None
   ```
   Every Phase 1/2 test that calls `repo.get(profile_id)` breaks.
   Every in-memory test constructing a `ProfileRepository` fake
   needs updating. The 157-test regression baseline becomes
   churn rather than signal.

2. **Additive extension** — leave the existing methods intact and
   add `*_for_user` variants alongside:
   ```python
   def get(self, profile_id: str) -> ProfileRecord | None
   def get_for_user(self, profile_id: str, user_id: str) -> ProfileRecord | None
   ```
   Phase 1/2 tests keep using `get`, `create`, etc. Phase 3 handlers
   switch to `create_for_user`, `get_for_user`, etc.

## Decision

**Additive extension.**

- Every existing Protocol method stays untouched in signature and
  semantics.
- A parallel set of `*_for_user` methods takes the same arguments plus
  `user_id` and scopes every lookup or mutation to rows owned by that
  user.
- Phase 3 handlers call ONLY the `_for_user` variants, passing
  `current_user.id`.
- In-memory repositories track ownership via a sidecar `_owners` dict
  (`profile_id -> user_id`) rather than adding a `user_id` field to
  the `Record` dataclasses. Avoids churning every Record construction
  site in Phase 1 code.
- SQL repositories add `user_id = user_id` to the WHERE clause on
  every ownership-filtered query.
- Roadmap ownership flows transitively through `analyses.user_id`
  because `roadmaps` has no `user_id` column; `get_for_user` on the
  SQL backend is a JOIN.

## Consequences

**Easier:**

- The 157 Phase 1/2 tests continue to exercise the original methods
  without a single assertion change. They remain the regression
  baseline they were designed to be.
- New Phase 3 integration tests opt in via `authenticated_client` —
  a mechanical fixture swap with no body changes (tests/integration
  Phase 1/2 files only changed in their parameter name).

**Harder:**

- Two code paths per repository during Phase 3's lifetime:
  `create` and `create_for_user`, both valid, both tested. After
  Phase 3, the "breaking cleanup" work (collapse the surface to
  `*_for_user` only) is a follow-up. Deferred intentionally.
- SQL repos' `create()` method now raises `RuntimeError` after
  migration 0002 makes `user_id` NOT NULL — if someone forgets to
  update a call site to `create_for_user`, they get a loud runtime
  error rather than a confusing IntegrityError from the DB.

**Constrained:**

- The ProfileRecord / AnalysisRecord / RoadmapRecord dataclasses
  don't carry `user_id`. Anyone reaching into a Record expecting
  ownership info won't find it. That's intentional — ownership is
  a repository concern, not a core-domain concern.
