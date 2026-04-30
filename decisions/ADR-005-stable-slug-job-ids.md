# ADR-005: Stable slug IDs for jobs

- **Status:** Accepted
- **Date:** 2026-04-30
- **Phase:** 1 — REST API Foundation

## Context

Three options to identify jobs over HTTP:

1. **Positional index** (`/api/v1/jobs/3`) — trivial to implement but
   breaks catastrophically if `data/jobs.json` ever reorders. A
   cached `analysis.job_id = 3` would suddenly reference a different
   job after a deploy.
2. **UUID generated at load time** — stable within one process run,
   but regenerated every app startup. Any stored `AnalysisRecord`
   that references `job_id=<uuid>` is immediately dangling after a
   process restart.
3. **Slug derived from the title** — `"Backend Developer"` →
   `"backend-developer"`. Stable as long as `data/jobs.json` is
   stable; survives process restarts; human-readable in URLs.

Collisions are possible (two jobs with identical titles). The API
needs to handle them deterministically so id assignment is a pure
function of the input list.

## Decision

Assign **slugified IDs from the job title** at load time. The
slugifier (`app/repositories/job_repo.py::_slugify`) lowercases,
collapses non-alphanumeric runs to hyphens, and strips leading/trailing
hyphens. Empty or punctuation-only titles fall back to `"job"`.

Collisions are disambiguated in **load order** by appending `-2`,
`-3`, etc. Stability across process restarts is guaranteed as long as
the underlying `jobs.json` preserves entry order — verified by a unit
test that builds two repo instances from the same list and asserts
identical slug sequences.

## Consequences

**Easier:**

- Human-readable URLs: `/api/v1/jobs/backend-developer` reads
  naturally in logs, debug dashboards, and commit messages.
- Cross-phase stability: when Phase 2 moves jobs to Postgres, the
  seed script can preserve these slugs as the primary key. Cached
  analysis records that reference a slug keep working.
- Deterministic: given the same `jobs.json`, the slug map is
  identical across machines and runs.

**Harder:**

- A slug isn't globally unique across resource types — `backend-developer`
  is only meaningful under `/api/v1/jobs/`. If the project ever needs
  opaque global identifiers (e.g. for sharable cross-resource links),
  we layer a uuid on top; the slug stays as a secondary key.

**Constrained:**

- Renaming a job title in `jobs.json` changes its slug and breaks any
  stored `AnalysisRecord` that references it. Documented as a known
  limitation of synthetic seed data; real production data would go
  through a migration.
