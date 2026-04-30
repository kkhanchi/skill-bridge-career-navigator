# ADR-011: Only jobs migrated to DB in Phase 2 (catalog-vs-DB boundary)

- **Status:** Accepted
- **Date:** 2026-04-30
- **Phase:** 2 — Persistence

## Context

Three JSON files ship with the synthetic data:

- `data/jobs.json` — 10 job postings (the search/filter surface)
- `data/skill_taxonomy.json` — ~64 skills for resume parsing
- `data/learning_resources.json` — ~97 courses/certifications

Phase 2's goal was to replace in-memory repositories with a DB.
Which of these three catalogs belong in the DB?

Options:

1. **Migrate all three** — `jobs`, `skills`, `learning_resources`
   tables. Two more migrations, two more seed paths, two more
   places to keep in sync.
2. **Migrate only jobs** — the one catalog that handlers query
   with filters (`?keyword=...&skill=...`) and that benefits from
   indexes. Leave taxonomy + resources as startup-loaded JSON.
3. **Migrate only user-generated data (profiles, analyses,
   roadmaps)** — keep all three catalogs as JSON. Smallest
   schema; widest gap between dev and prod.

## Decision

Migrate only `jobs`. Taxonomy and learning resources stay as
startup-loaded JSON in `ext.taxonomy` and `ext.resources`.

- Jobs get an index-friendly schema because `GET /api/v1/jobs`
  is the only endpoint that filters a catalog.
- Resume parsing is a per-request lookup against an ~64-item
  list — scanning in-memory is fine.
- Roadmap generation does a lookup against ~97 resources — same
  story; in-memory is more than fast enough at this scale.

## Consequences

**Easier:**

- Smaller migration surface in Phase 2. One `jobs` table, one
  seed path, one R5.4 slug-stability property test to prove the
  Phase 1 → Phase 2 transition doesn't lose ids.
- Dev bring-up is short: `alembic upgrade head`, `python -m
  scripts.seed_db`, `python run.py`. No extra "seed taxonomy"
  or "seed resources" commands.
- Catalog updates (adding a new skill to the taxonomy, adding
  a course to learning_resources) stay as JSON edits reviewed
  in PR. No DB migration for catalog content — the source of
  truth is the file.

**Harder:**

- If we ever want to edit catalogs without redeploying (an
  admin UI, for example), taxonomy and learning_resources have
  to be migrated to tables. This is the revisit trigger;
  deferred to Phase 5 or later.
- Taxonomy and resources live in two places at once — the
  file AND the loaded Python lists on `ext`. Changes to the
  file require an app restart to take effect.

**Constrained:**

- The seed script is explicitly jobs-only (R5.5). If any other
  seed path is added, it goes in a sibling script (e.g.
  `scripts/seed_taxonomy.py`), not inside `seed_db.py`.
- The in-memory → SQL transition is preserved for jobs through
  the R5.4 slug-stability property. Cached `AnalysisRecord.
  job_id` values from Phase 1 still resolve after the DB lands,
  because the slug logic is shared.
