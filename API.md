# SkillBridge REST API — Phase 1 & 2 Reference

Base URL (local dev): `http://localhost:5000`

All resource endpoints live under `/api/v1/`. `/health` is
intentionally unversioned so load balancers and monitoring tools can
probe the service without caring about API versions.

## Persistence (Phase 2)

The API now reads/writes a relational database when a `DATABASE_URL`
is configured. Endpoint contracts are **identical** to Phase 1 —
same paths, status codes, error envelopes, correlation-id behavior —
but data now survives process restarts.

```bash
# First-time setup (dev SQLite):
APP_ENV=dev alembic upgrade head
python -m scripts.seed_db

# Or omit DATABASE_URL entirely to run on the Phase 1 in-memory
# backend (data vanishes on restart, single-worker only):
REPO_BACKEND=memory python run.py
```

Production uses Postgres: set `DATABASE_URL=postgresql://...` and
`gunicorn -w N` is now safe (per-worker in-memory state is no longer
an issue on the SQL backend).

See [`decisions/ADR-007`](decisions/ADR-007-dual-backend-repositories.md)
for the dual-backend design,
[`ADR-008`](decisions/ADR-008-alembic-workflow.md) for the migration
workflow, and [`ADR-011`](decisions/ADR-011-catalog-vs-db-boundary.md)
for why only jobs moved to the DB.

## Conventions

### Error response shape

Every 4xx / 5xx response matches this envelope:

```json
{
  "error": {
    "code": "VALIDATION_FAILED",
    "message": "Request validation failed",
    "details": { "errors": [ ... ] }
  }
}
```

`details` is optional and absent for most error codes. Valid `code`
values are drawn from the closed set documented in `decisions/ADR-004`
and `app/utils/errors.py`.

### Correlation ID

Every response carries an `X-Correlation-ID` header. If your request
includes one, the API reuses it; otherwise the API generates one. Use
this value when grepping through logs to trace a single request.

```bash
curl -i http://localhost:5000/health

HTTP/1.1 200 OK
Content-Type: application/json
X-Correlation-ID: 7f94e7c5b3a24fe381ddb5a9c7a1e4c2

{"status":"ok"}
```

With an inbound id:

```bash
curl -i -H "X-Correlation-ID: debug-trace-001" http://localhost:5000/health
# -> X-Correlation-ID: debug-trace-001
```

---

## Endpoints

### Health

#### `GET /health`

Unconditional 200. No side effects.

```bash
curl http://localhost:5000/health
# {"status":"ok"}
```

---

### Profiles

#### `POST /api/v1/profiles`

```bash
curl -X POST http://localhost:5000/api/v1/profiles \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Jane Doe",
    "skills": ["Python", "SQL", "Git"],
    "experience_years": 3,
    "education": "Bachelor'\''s in CS",
    "target_role": "Backend Developer"
  }'
```

Returns **201** with the created profile including a generated `id`,
`created_at`, and `updated_at`.

Failure modes: **400 VALIDATION_FAILED** for schema violations,
**400 PROFILE_INVALID** for domain-level errors (e.g. all skills
duplicates).

#### `GET /api/v1/profiles/{id}`

```bash
curl http://localhost:5000/api/v1/profiles/<id>
```

**200** with the profile, **404 NOT_FOUND** otherwise.

#### `PATCH /api/v1/profiles/{id}`

Partial update. At least one field must be present.

```bash
curl -X PATCH http://localhost:5000/api/v1/profiles/<id> \
  -H 'Content-Type: application/json' \
  -d '{"added_skills": ["Docker"], "target_role": "Senior Backend Developer"}'
```

Supported fields: `added_skills`, `removed_skills`, `name`,
`experience_years`, `education`, `target_role`.

#### `DELETE /api/v1/profiles/{id}`

```bash
curl -X DELETE -i http://localhost:5000/api/v1/profiles/<id>
# HTTP/1.1 204 No Content
```

Does not cascade — analyses and roadmaps that referenced this profile
remain accessible by their own ids. Documented Phase 1 limitation.

---

### Resume parsing

#### `POST /api/v1/resume/parse`

Extract taxonomy skills from free-form resume text. Pure read
(no side effects). Text is capped at 50_000 characters.

```bash
curl -X POST http://localhost:5000/api/v1/resume/parse \
  -H 'Content-Type: application/json' \
  -d '{"text": "3 years of Python, SQL, and Docker experience..."}'
# {"skills": ["Python", "SQL", "Docker"]}
```

---

### Jobs

#### `GET /api/v1/jobs`

Paginated list. Defaults: `page=1`, `limit=20`. Limit range: [1, 100].

```bash
# All jobs (10 in the seed catalog)
curl 'http://localhost:5000/api/v1/jobs'

# Filter by keyword (matches title)
curl 'http://localhost:5000/api/v1/jobs?keyword=developer'

# Filter by required skill
curl 'http://localhost:5000/api/v1/jobs?skill=Python'

# Pagination
curl 'http://localhost:5000/api/v1/jobs?page=2&limit=3'
```

Response envelope:

```json
{
  "items": [ ... ],
  "meta": { "page": 1, "limit": 20, "total": 10, "pages": 1 }
}
```

Out-of-range pages return empty `items` with the correct `meta.total`
and `meta.pages` — the handler does not raise 404 for overflow.

#### `GET /api/v1/jobs/{slug}`

Slugs are stable (derived from title, disambiguated by load order).

```bash
curl http://localhost:5000/api/v1/jobs/backend-developer
```

Returns **200** with the job, **404 JOB_NOT_FOUND** otherwise.

---

### Analyses

#### `POST /api/v1/analyses`

Run a gap analysis between a stored profile and a stored job. The
response embeds the `gap` (matched/missing skills + match percentage)
and the `categorization` (groups + plain-English summary) produced by
either the Groq API or the rule-based fallback (`is_fallback: true` in
that case).

```bash
curl -X POST http://localhost:5000/api/v1/analyses \
  -H 'Content-Type: application/json' \
  -d '{"profile_id": "<profile id>", "job_id": "backend-developer"}'
```

Returns **201**. Failure modes checked in order:

- **400 VALIDATION_FAILED** if body is malformed.
- **404 PROFILE_NOT_FOUND** — profile check runs first.
- **404 JOB_NOT_FOUND** — then the job check.

Groq failures never produce a 5xx. If Groq is unreachable or slow,
the response still succeeds with `categorization.is_fallback: true`.

#### `GET /api/v1/analyses/{id}`

```bash
curl http://localhost:5000/api/v1/analyses/<id>
```

**200** or **404 ANALYSIS_NOT_FOUND**.

---

### Roadmaps

#### `POST /api/v1/roadmaps`

Build a phased learning roadmap from an existing analysis.

```bash
curl -X POST http://localhost:5000/api/v1/roadmaps \
  -H 'Content-Type: application/json' \
  -d '{"analysis_id": "<analysis id>"}'
```

Returns **201** with three phases (`Month 1-2`, `Month 3-4`,
`Month 5-6`), each containing learning resources with stable uuid
identifiers.

#### `PATCH /api/v1/roadmaps/{id}/resources/{resource_id}`

Flip a resource's `completed` flag.

```bash
curl -X PATCH \
  http://localhost:5000/api/v1/roadmaps/<id>/resources/<resource_id> \
  -H 'Content-Type: application/json' \
  -d '{"completed": true}'
```

Returns **200** with the updated roadmap. The handler distinguishes
**404 ROADMAP_NOT_FOUND** from **404 RESOURCE_NOT_FOUND** (the latter
when the roadmap exists but the resource id does not).

---

## Error envelope example

```bash
curl -i http://localhost:5000/api/v1/profiles/does-not-exist

HTTP/1.1 404 NOT FOUND
Content-Type: application/json
X-Correlation-ID: 1a2b3c...

{
  "error": {
    "code": "NOT_FOUND",
    "message": "Profile not found"
  }
}
```

---

## Running the API

```bash
# Development (Flask dev server, auto-reload, debug tracebacks)
cd skill-bridge
python run.py

# Production (single worker — in-memory repos are per-process in Phase 1)
gunicorn -w 1 wsgi:application
```

See `decisions/ADR-003` for why single-worker is required in Phase 1.
