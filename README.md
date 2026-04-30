# Skill-Bridge Career Navigator

[![CI](https://github.com/kkhanchi/skill-bridge-career-navigator/actions/workflows/ci.yml/badge.svg)](https://github.com/kkhanchi/skill-bridge-career-navigator/actions/workflows/ci.yml)
[![Build & Publish](https://github.com/kkhanchi/skill-bridge-career-navigator/actions/workflows/build-and-publish.yml/badge.svg)](https://github.com/kkhanchi/skill-bridge-career-navigator/actions/workflows/build-and-publish.yml)
[![Coverage](https://img.shields.io/badge/coverage-91%25-brightgreen)](https://github.com/kkhanchi/skill-bridge-career-navigator/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![mypy: strict](https://img.shields.io/badge/mypy-strict-blue)](https://mypy.readthedocs.io/)

🌐 **[Live API](https://skillbridge-api-4foe.onrender.com)** — free-tier deploy on Render. First visit after ~15 min of idle may take up to 30 s to cold-start.

🎥 **[Watch the Video Presentation](https://drive.google.com/file/d/1fNGElHl7o5CnxIvw-AoDvFN7fmro8Gxe/view?usp=drive_link)**

🚀 **[Try the Streamlit Reference UI](https://skill-bridge-career-navigator-kaczqrtu9jxfbxlywg9miu.streamlit.app/)**

---

## Candidate Name
Kartik Khanchi

## Scenario Chosen
**Scenario 2: Skill-Bridge Career Navigator**

## Estimated Time Spent
~5 hours

---

## The Problem

Students and early-career professionals often find a "skills gap" between their academic knowledge and the specific technical requirements of job postings. Navigating multiple job boards and certification sites makes it difficult to see a clear path from their current skill set to their "dream role."

There is no single tool that takes what you know, compares it against what the market demands, and tells you exactly what to learn and in what order. The result is wasted time, scattered effort, and a lack of confidence when applying for roles.

## What We're Solving

We built a career navigation platform that:

1. **Identifies your skills** — paste your resume or manually select from a taxonomy of 60+ skills
2. **Compares against real job requirements** — a catalog of 10 job roles (Backend Dev, Data Scientist, DevOps Engineer, etc.) with required and preferred skills
3. **Shows your exact skill gaps** — a clear dashboard showing what you have, what you're missing, and your match percentage
4. **Uses AI to categorize and summarize gaps** — powered by Groq (Llama 3.3 70B), the AI groups your missing skills into categories (Programming, Cloud, Data & ML, Soft Skills) and gives you a plain-English summary of where you stand
5. **Generates a personalized learning roadmap** — a phased plan (Month 1-2, 3-4, 5-6) with specific courses, projects, and certifications to close each gap
6. **Tracks your progress** — mark resources as completed, add new skills, and re-analyze to see your match percentage improve

## Target Audience

- **Recent Graduates** looking to understand which certifications make them competitive
- **Career Switchers** needing to identify transferable skills between industries
- **Mentors** looking for a data-backed way to guide their mentees' development

## Why This Matters

Without a tool like this, the typical workflow is: browse job postings → feel overwhelmed by requirements → Google random courses → lose motivation. Skill-Bridge replaces that with a structured, AI-assisted path from "where I am" to "where I want to be."

---

## Quick Start

### Prerequisites
- Python 3.10+
- A Groq API key (free at [console.groq.com](https://console.groq.com)) — optional, the app works without it using rule-based fallback

### Run commands

The project ships two frontends: the original Streamlit UI and the new Flask REST API introduced in Phase 1.

```bash
cd skill-bridge
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your GROQ_API_KEY (optional)
```

**Option 1 — Streamlit reference UI** (original prototype):
```bash
streamlit run app.py
```

**Option 2 — Flask REST API** (Phases 1 & 2):
```bash
# First-time setup (Phase 2 persistence):
APP_ENV=dev alembic upgrade head        # create schema in skill-bridge-dev.db
python -m scripts.seed_db               # load jobs catalog from data/jobs.json

# Development server
python run.py

# Production-style with gunicorn
# Phase 2 onwards (SQL backend): multi-worker is safe
gunicorn -w 4 wsgi:application
# Phase 1-style memory backend (REPO_BACKEND=memory): single worker only
REPO_BACKEND=memory gunicorn -w 1 wsgi:application
```

See [`API.md`](API.md) for endpoint reference and curl recipes, and [`.kiro/specs/`](../.kiro/specs/) for the full per-phase design, requirements, and task breakdowns.

### Test Commands
```bash
cd skill-bridge
pytest tests/ -v
```

---

## Phase 3 — Authentication & Authorization

Phase 3 turns SkillBridge into a multi-user system. Every profile, analysis, and roadmap is now owned by exactly one user; cross-tenant reads and writes return 404 (ADR-015 anti-enumeration). Authentication is JWT-based with short-lived stateless access tokens and stateful rotating refresh tokens.

**What shipped in Phase 3:**
- 5 new endpoints under `/api/v1/auth/*`:
  - `POST /register` — 201 with `{user, access, refresh}`, 409 on duplicate email
  - `POST /login` — 200 with `{user, access, refresh}`; constant-time verify on the unknown-email branch closes the account-enumeration timing side channel
  - `POST /refresh` — 200 with a fresh `{access, refresh}` pair; presenting the same refresh twice returns 401 (rotation is one-shot)
  - `POST /logout` — 204, idempotent; revokes the refresh's jti but leaves the access token alone until its natural 15-min expiry
  - `GET /me` — 200 with the current user's public projection
- `@require_auth` decorator on every `/api/v1/profiles`, `/analyses`, `/roadmaps` handler; handlers receive a `current_user` kwarg and scope every repo call through `*_for_user` variants (ADR-014 — additive extension keeps the 157 prior tests green)
- Argon2id password hashing via `argon2-cffi` with config-driven cost parameters (ADR-012)
- Per-IP rate limits on auth endpoints — register 5/hour, login 10/minute, refresh 30/minute — via `flask-limiter` in in-memory storage (ADR-016)
- CORS configured via `CORS_ORIGINS` env var — prod requires explicit origins, dev defaults to `*` (ADR-017)
- Migrations 0002 (flip `profiles.user_id` / `analyses.user_id` to NOT NULL + CASCADE) and 0003 (new `refresh_tokens` table)
- 268 tests total: +63 new Phase 3 tests including an auth integration suite, multi-tenant isolation suite, rate-limit suite, and 5 new Hypothesis property tests (refresh rotation one-shot, logout idempotency, access-TTL invariant, multi-tenant stateful machine, envelope closure)

### Environment variables

| Var | Required in | Default | Notes |
|-----|-------------|---------|-------|
| `JWT_SECRET` | **prod** | dev literal | `init_extensions` raises RuntimeError in prod if empty. Dev falls back to `"dev-secret-do-not-use-in-prod"` with a startup warning. |
| `CORS_ORIGINS` | no | `""` in prod, `"*"` in dev | Empty disables CORS entirely. CSV for an exact-match allowlist. |
| `ACCESS_TTL_SECONDS` | no | 900 (15 min) | Access token lifetime. |
| `REFRESH_TTL_SECONDS` | no | 1_209_600 (14 days) | Refresh token lifetime. |
| `ARGON2_TIME_COST` | no | 2 | See [OWASP's argon2 guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html) to tune for prod. |
| `ARGON2_MEMORY_COST` | no | 65536 (KiB) | |
| `ARGON2_PARALLELISM` | no | 4 | |

### Multi-worker rate-limit caveat

The rate limiter uses in-memory storage for Phase 3 (ADR-016). A deployment with N gunicorn workers effectively multiplies every quota by N — running 4 workers turns the "5 registrations/hour per IP" limit into 20 across the fleet. Documented failure mode; for a production deployment behind a proxy, either cap to a single worker or swap the limiter's storage URI to Redis (`storage_uri="redis://..."` — API-compatible, one-line change).

### Cross-tenant behaviour

A request from user B against a resource owned by user A returns `404 NOT_FOUND` — same envelope body as a genuinely-missing resource. The ownership filter is baked into every `*_for_user` query so wrong-owner is indistinguishable from doesn't-exist (ADR-015). Register, by contrast, still leaks email existence via `409 EMAIL_TAKEN` — accepted Phase 3 tradeoff, documented in ADR-015.

See `.kiro/specs/phase-3-auth/` for full design and requirements, and ADRs [012](decisions/ADR-012-argon2-password-hashing.md), [013](decisions/ADR-013-jwt-hs256-rotating-refresh.md), [014](decisions/ADR-014-additive-protocol-extension.md), [015](decisions/ADR-015-404-over-403.md), [016](decisions/ADR-016-flask-limiter-in-memory.md), [017](decisions/ADR-017-cors-env-allowlist.md) for the non-trivial choices.

---

## Phase 5 — Docker, CI/CD, Deployment

Phase 5 takes the application from "green CI" to "a public URL." Zero runtime behaviour change — everything shipped is packaging and operations.

**What shipped in Phase 5:**
- **Multi-stage Dockerfile** (`skill-bridge/Dockerfile`): Python 3.12-slim base, `builder` stage installs deps with `build-essential + libpq-dev`, `runtime` stage copies the installed env over and drops to `libpq5` only. Non-root user (UID 10001), fixed `$PORT` default of 5000. Target size under 250 MB.
- **`entrypoint.sh`**: POSIX sh, `set -e`, runs `alembic upgrade head` then `exec gunicorn --workers 1 --bind 0.0.0.0:$PORT wsgi:application`. Exec is critical for signal propagation — SIGTERM goes straight to gunicorn.
- **`docker-compose.yml`**: local-dev orchestration (API + Postgres 16 Alpine). Compose waits for Postgres to be healthy (`pg_isready`) before starting the API, so the migration never fires against a not-ready DB. Named `postgres_data` volume survives `compose down`.
- **GitHub Actions `build-and-publish.yml`**: on every push to main, blocks until the Phase 4 `ci.yml` quality gate passes for the same SHA, then builds the image and pushes to `ghcr.io/kkhanchi/skill-bridge-career-navigator`. Tags: `latest`, `sha-<short>`, `vX.Y.Z`. Layer caching via `type=gha mode=max`.
- **`render.yaml` blueprint**: declarative service + managed Postgres definition. Web service runs the Docker image, `preDeployCommand: alembic upgrade head` gates every deploy on migration success (fail-closed if a migration breaks). `JWT_SECRET` and other secrets live in Render's dashboard, never in the blueprint.
- **Single ADR-019** consolidating all Phase 5 decisions.

### Deploy workflow

```
push to main
    ↓
GitHub Actions: ci.yml (lint + mypy + tests + coverage)
    ↓ green
GitHub Actions: build-and-publish.yml
    ↓
ghcr.io/kkhanchi/skill-bridge-career-navigator:latest
    ↓
Render (pulls on deploy) → alembic upgrade head → gunicorn → health check passes → traffic shifts
```

### Run locally via Docker

```bash
cd skill-bridge
cp .env.example .env       # set JWT_SECRET
make compose-up            # docker compose up -d, builds the image
make smoke                 # curl /health, asserts 200
make compose-down          # teardown; add -v to wipe the postgres volume
```

### Architecture

```
┌────────────────┐                ┌───────────────────────────────────┐
│  Streamlit UI  │                │  Render (free tier, Oregon)        │
│  app.py via    │──── HTTPS ────▶│  ┌─────────────────────────────┐   │
│  api_client.py │                │  │  skillbridge-api container   │   │
└────────┬───────┘                │  │  gunicorn -w 1 on $PORT      │   │
         │                        │  │  image: ghcr.io/.../:latest  │   │
┌────────┴───────┐                │  └──────────────┬──────────────┘   │
│  Browser /     │                │                 │                   │
│  curl          │──── HTTPS ────▶│                 ▼                   │
└────────────────┘                │  ┌─────────────────────────────┐   │
                                  │  │  skillbridge-db (managed)    │   │
                                  │  │  Postgres 16 free tier       │   │
                                  │  └─────────────────────────────┘   │
                                  └───────────────────────────────────┘
                                              ▲
                                              │ docker pull
                                              │
                                 ┌────────────┴───────────┐
                                 │  ghcr.io/<owner>/<repo>│
                                 │  :latest :sha-xxx      │
                                 └────────────▲───────────┘
                                              │ docker push
                                              │
                                 ┌────────────┴───────────┐
                                 │  GitHub Actions        │
                                 │  ci.yml → build-and-   │
                                 │  publish.yml           │
                                 └────────────────────────┘
```

Phase 6 adds the Streamlit UI path (top-left). The API serves both
browser/curl traffic and the Streamlit client equivalently — the
client is just another HTTPS consumer of `/api/v1/*`.


### Cold start caveat

Render's free tier spins down services after ~15 minutes of idle traffic. The first request after a cold stop takes up to 30 s while the container starts and `alembic upgrade head` runs. Warm requests respond in milliseconds.

See [ADR-019](decisions/ADR-019-deploy-architecture.md) for the full architecture decision record covering Docker, GHCR, Render, and the stdout-logs-over-observability-stack tradeoff.

---

## Phase 4 — Testing & Quality

Phase 4 formalizes the development loop around Phases 1-3's code. Zero runtime behaviour change — what's new is enforcement, measurement, and tooling.

**What shipped in Phase 4:**
- **Ruff** for lint + format (consolidates Black + isort + flake8). 100-char line length, `E`/`W`/`F`/`I`/`B`/`UP`/`SIM` rule families, curated ignores documented in `pyproject.toml`.
- **mypy** with `strict = true` globally across `app/`. Per-module escape hatches for the Streamlit shim modules at the repo root and `app.core.ai_engine` (Groq SDK has no stubs). The Flask view-handler modules relax `no-untyped-def` because handler chains through `@require_auth + @_with_limit + @validate_body + @bp.post` don't propagate types cleanly under strict mode.
- **pytest-cov** with branch coverage and an 80% floor enforced on every run. Current state: 91% total coverage; no file below 66%.
- **factory-boy + Faker** for six ORM factories covering every Phase 2/3 table (`UserFactory`, `JobFactory`, `ProfileFactory`, `AnalysisFactory`, `RoadmapFactory`, `RefreshTokenFactory`). `SubFactory` auto-creates FK parents; `Sequence` prevents email collisions. 6 round-trip tests plus one real-integration refactor in `test_sql_persistence.py` prove the factories slot into both the detached and HTTP test paths.
- **pre-commit hooks** running Ruff lint, Ruff format, trailing whitespace, end-of-file fixer, and YAML check on every `git commit`. No pytest hook — test runtime is too long for commit-time.
- **GitHub Actions CI** (`.github/workflows/ci.yml`) running the full gate on every push and every PR to `main`. Pip cache keyed on `requirements.txt`; `coverage.xml` uploaded as a workflow artifact.
- **Makefile** with `install`, `hooks`, `lint`, `format`, `format-check`, `typecheck`, `test`, `check`, `clean`. `make check` mirrors CI exactly.
- **Single consolidated ADR** (012-018? actually ADR-018) documenting the tool choices as one coherent decision.

Test count: **274** (Phase 3's 268 plus 6 factory round-trips). All property tests from Phases 1–3 continue to run on every CI build.

### Quality & CI

One command runs the full gate locally:

```bash
cd skill-bridge
make check     # ruff + ruff-format-check + mypy + pytest (with coverage)
```

Or install the pre-commit hooks so every `git commit` catches the fast subset automatically:

```bash
make hooks     # or: pre-commit install
```

CI workflow: [`.github/workflows/ci.yml`](.github/workflows/ci.yml). See [ADR-018](decisions/ADR-018-tooling-choices.md) for the tooling decision record.

---

## Phase 2 — Persistence
Phase 2 replaces Phase 1's in-memory repositories with a real relational database. Both backends coexist behind one `typing.Protocol` seam (see [ADR-007](decisions/ADR-007-dual-backend-repositories.md)), and backend selection is driven at app-factory time by environment variables:

```bash
# No DATABASE_URL set -> in-memory repos (Phase 1 flow, single-worker)
python run.py

# SQLite file -> SQL backend (dev default)
DATABASE_URL="sqlite:///./skillbridge.db" python run.py

# Postgres -> SQL backend (prod)
DATABASE_URL="postgresql://user:pw@host/db" gunicorn -w 4 wsgi:application

# Force memory even with a DATABASE_URL in scope (benchmarks, tests)
REPO_BACKEND=memory python run.py
```

**What shipped in Phase 2:**
- SQLAlchemy 2.x declarative ORM (`app/db/models.py`) covering 5 tables (users, profiles, jobs, analyses, roadmaps)
- Alembic migrations under `migrations/` with one initial migration + a CI-friendly round-trip smoke test
- Second family of repositories (`SqlAlchemy*Repository`) conforming to the Phase 1 Protocols — handlers didn't change
- Request-scoped session hooks (`before_request` open / `teardown_request` commit or rollback + close) — memory backend stays zero-overhead
- Idempotent `scripts/seed_db.py` that loads `data/jobs.json` into the `jobs` table with slug ids matching Phase 1's in-memory repo
- JSON columns portable via `JSON().with_variant(JSONB(), "postgresql")` ([ADR-010](decisions/ADR-010-jsonb-portability.md))
- 157 tests, including 5 Hypothesis property tests: repository-backend equivalence (the load-bearing proof the Protocol seam works), seed idempotency, slug stability, SQL pagination partition, JSONB round-trip

The `users` table is created now but `user_id` foreign keys stay nullable until Phase 3 wires authentication.

---

## Phase 1 — REST API Foundation

The project is evolving from a Streamlit prototype into a production-quality backend. Phase 1 adds a Flask REST API under `/api/v1/` that exposes the existing business logic over HTTP.

**What shipped in Phase 1:**
- 12 endpoints (profiles CRUD, resume parse, jobs list/detail, analyses, roadmaps + resource PATCH, health) under `/api/v1/`
- Flask application factory with environment configs (dev/test/prod)
- Pydantic v2 request/response validation with a uniform `{"error": {"code", "message"}}` envelope
- Per-request correlation IDs flowing through structured JSON logs and the `X-Correlation-ID` response header
- Repository pattern behind `typing.Protocol` interfaces (Phase 2 slots SQLAlchemy in without touching handlers)
- 89 tests: unit + integration + 5 Hypothesis property tests covering round-trip, pagination partition, case-insensitivity, completion monotonicity, and error envelope shape

See [`API.md`](API.md) for the endpoint reference, the [`decisions/`](decisions/) folder for ADRs explaining the non-trivial choices, and [`.kiro/specs/`](../.kiro/specs/) for the full per-phase specs.

The Streamlit UI continues to work unchanged via root-level shim modules (see [ADR-006](decisions/ADR-006-streamlit-shims.md)).

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Frontend/UI | Streamlit |
| AI Engine | Groq API (Llama 3.3 70B) |
| Fallback AI | Rule-based keyword categorizer |
| Language | Python 3.12 |
| Testing | pytest + Hypothesis |
| Data | Synthetic JSON (no real PII) |

## Core Features (MVP)

- **Profile Creation** — manual entry or resume text parsing with skill extraction
- **Job Catalog** — 10 synthetic job postings with search/filter
- **Gap Analysis** — required vs preferred skill matching with match percentage
- **AI Categorization** — Groq-powered skill grouping and summary (with rule-based fallback)
- **Learning Roadmap** — phased plan with courses, projects, certifications
- **Progress Tracking** — mark completed, update skills, re-analyze

## AI Integration & Fallback

The AI engine uses Groq's free-tier Llama 3.3 70B model to:
- Categorize missing skills into meaningful groups
- Generate a natural-language summary of the user's strengths and gaps

**Fallback:** If the API key is missing, the API errors, or the request times out (>5 seconds), the system automatically falls back to a rule-based keyword categorizer that groups skills using a predefined mapping. The UI clearly labels when fallback is active.

## Data Safety
- All data is synthetic — no real personal information
- API keys stored in `.env` (gitignored)
- `.env.example` provided with placeholder values

---

## Phase 6 — Streamlit Integration with the Deployed API (current)

Phase 6 cuts the Streamlit UI over to the Phase 5 live API. The reference UI at `app.py` no longer imports Phase 0 core modules for its data path; it talks HTTP to `https://skillbridge-api-4foe.onrender.com` via a new `api_client.py`.

**What shipped in Phase 6:**

- **`api_client.py`** — a single `ApiClient` class with 16 methods (one per Phase 1–3 endpoint), a 5-leaf error taxonomy (`ApiClientError`, `ApiServerError`, `ApiConnectionError`, `AuthExpiredError`, `RateLimitedError`, all sharing an `ApiError` base), reactive token refresh on 401 bounded at 3 HTTP requests per authenticated call, and lazy cold-start warmup. The client is Streamlit-agnostic — `app.py` owns `st.session_state` and passes tokens in via `set_tokens`.
- **Auth sidebar** in `app.py` — register / login tabs, current-user display, logout button. Tokens live in `st.session_state` per-session (no cookies / localStorage by design, see ADR-020 §10).
- **Two-mode `app.py`** controlled by `SKILL_BRIDGE_OFFLINE`. Online mode (default) talks HTTP; offline mode (`SKILL_BRIDGE_OFFLINE=1`) falls back to direct core-module imports for zero-infra laptop demos. R9 Option B.
- **Cold-start spinner** on the first API call of a session so the ~30 s Render free-tier cold start doesn't look broken. `warmup()` retries `/health` with backoff [1, 2, 4, 8, 16] seconds; gives up after 6 attempts.
- **Configurable API URL** via `st.secrets["API_BASE_URL"]` → `os.environ["API_BASE_URL"]` → `http://localhost:5000` ladder.
- **`ADR-020`** — single ADR consolidating all Phase 6 decisions: hand-rolled client over codegen, reactive refresh over proactive, error taxonomy design, rerun-model session-state reattachment, logout 2 s timeout, Legacy_Shims disposition (Option B).
- **63 new tests** covering 16 happy-path endpoint tests, 36 internals tests (error taxonomy, reactive refresh, warmup, URL ladder), 3 Hypothesis properties (P1 refresh bound, P3 URL ladder, P4 profile round-trip), 6 P2 logout idempotency tests at the handler layer. Phase 5's 274 still pass.

### Run both services locally

1. Start the API (from `skill-bridge/`):
   ```
   make compose-up
   ```
   This brings up Postgres 16 + the Flask API on port 5000 via docker-compose.

2. Point the Streamlit app at it:
   ```
   export API_BASE_URL=http://localhost:5000
   streamlit run app.py
   ```

3. Register an account in the sidebar, log in, and use the UI as normal. All state persists server-side.

### Run against the deployed API

1. Set `API_BASE_URL` in `.streamlit/secrets.toml` (local) or the Streamlit Cloud secrets dashboard (prod):
   ```toml
   API_BASE_URL = "https://skillbridge-api-4foe.onrender.com"
   ```
2. `streamlit run app.py`. First call triggers the cold-start spinner (~30 s); subsequent calls are fast.

### Offline-only demo (no API required)

```
SKILL_BRIDGE_OFFLINE=1 streamlit run app.py
```

Falls back to the Phase 0–5 direct-core-import path. In-memory storage, no login required. Useful for reviewers running on a laptop with no infra.

### Phase 6 ADR

- [ADR-020: Streamlit integration with the deployed API](./decisions/ADR-020-streamlit-api-integration.md)

---

## AI Disclosure

- **Did you use an AI assistant?** Yes (Claude)
- **How did you verify suggestions?** Reviewed all generated code, ran tests, manually tested the UI flow
- **Example of a rejected suggestion:** The AI suggested using a SQLite database for storing user profiles and session data. I rejected this because Streamlit's built-in `st.session_state` was sufficient for a prototype demo, and adding a database layer would have added setup complexity and eaten into the timebox without meaningfully improving the demo experience.

## Tradeoffs & Prioritization

- **What did you cut?** Property-based tests (Hypothesis), visual polish, persistent storage, mock interview feature
- **What would you build next?** Real job board API integration, user accounts with database persistence, mock interview generator, resume PDF upload with OCR
- **Known limitations:** Session-based storage (data lost on refresh), synthetic job data only, Groq free tier rate limits (30 req/min)
