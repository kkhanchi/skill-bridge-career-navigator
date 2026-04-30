# SkillBridge Career Navigator

[![CI](https://github.com/kkhanchi/skill-bridge-career-navigator/actions/workflows/ci.yml/badge.svg)](https://github.com/kkhanchi/skill-bridge-career-navigator/actions/workflows/ci.yml)
[![Build & Publish](https://github.com/kkhanchi/skill-bridge-career-navigator/actions/workflows/build-and-publish.yml/badge.svg)](https://github.com/kkhanchi/skill-bridge-career-navigator/actions/workflows/build-and-publish.yml)
[![Coverage](https://img.shields.io/badge/coverage-91%25-brightgreen)](https://github.com/kkhanchi/skill-bridge-career-navigator/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![mypy: strict](https://img.shields.io/badge/mypy-strict-blue)](https://mypy.readthedocs.io/)

**Live API** — <https://skillbridge-api-4foe.onrender.com> (Render free
tier; first request after ~15 min idle takes up to 30 s to cold-start)

**Live UI** — <https://skill-bridge-career-navigator-kaczqrtu9jxfbxlywg9miu.streamlit.app>

**Video walkthrough** — <https://drive.google.com/file/d/1fNGElHl7o5CnxIvw-AoDvFN7fmro8Gxe/view?usp=drive_link>

---

## What it is

SkillBridge takes a user's skills and a target job, and produces a gap
analysis plus a phased learning roadmap. It started life as a Streamlit
prototype and has been rebuilt across six phases into a multi-tenant REST
API with JWT auth, a Postgres backend, a typed Python codebase, a
Docker-based deploy to Render, and a Streamlit client that talks to the
deployed API over HTTPS.

What's in the repo now:

- **Flask REST API** at `/api/v1/*` — 17 endpoints covering auth
  (register, login, rotating refresh, logout, me), jobs, resume parsing,
  profiles, analyses, and roadmaps.
- **Postgres 16** via SQLAlchemy 2.x + Alembic migrations. JSONB on
  Postgres, `JSON` on SQLite — one column definition, two dialects.
- **Argon2id passwords, HS256 JWTs** with stateless access (15 min) +
  stateful rotating refresh (14 days); one-shot rotation, constant-time
  verify against a dummy hash on unknown-email branches.
- **Streamlit client** (`app.py`) that talks HTTP to the live API via a
  hand-rolled `ApiClient` with reactive refresh, lazy cold-start warmup,
  and a five-leaf error taxonomy.
- **Quality gate**: Ruff (lint + format), mypy strict, pytest with 91%
  branch coverage and a hard 80% floor, 17 Hypothesis property tests
  across the phases.
- **Docker + Render deploy** — multi-stage image under 250 MB, non-root
  UID 10001, GHCR publish gated on CI, single-worker gunicorn.

Detailed rationale for every choice above lives in the
[ADR index](decisions/README.md) and [`DESIGN_DOCUMENT.md`](../DESIGN_DOCUMENT.md).
Phase-by-phase specs (requirements / design / tasks) are under
[`.kiro/specs/`](../.kiro/specs/).

## Architecture

```
┌────────────────┐        ┌──────────────────────────────────┐
│ Streamlit UI   │        │ Render (free tier, Oregon)       │
│ app.py         │ HTTPS  │ ┌──────────────────────────────┐ │
│ api_client.py  │────────▶│ skillbridge-api (Docker)     │ │
│                │        │ │ gunicorn -w 1               │ │
│ SKILL_BRIDGE_  │        │ │ Flask /api/v1/*             │ │
│ OFFLINE=1 ↴   │        │ └──────────────┬───────────────┘ │
│ direct imports │        │                │                  │
│ to app/core/*  │        │                ▼                  │
└────────────────┘        │ ┌──────────────────────────────┐ │
                          │ │ skillbridge-db (Postgres 16) │ │
                          │ └──────────────────────────────┘ │
                          └──────────────────────────────────┘
                                        ▲
                                        │ docker pull on deploy
                                        │
                          ┌─────────────┴─────────────────────┐
                          │ ghcr.io/<owner>/skill-bridge-...  │
                          └─────────────▲─────────────────────┘
                                        │ docker push
                          ┌─────────────┴─────────────────────┐
                          │ GitHub Actions                    │
                          │ ci.yml (blocking) →               │
                          │ build-and-publish.yml             │
                          └───────────────────────────────────┘
```

## Quickstart

Pick the mode that matches your situation.

### A. Streamlit UI against the deployed API (zero local setup)

```bash
export API_BASE_URL=https://skillbridge-api-4foe.onrender.com
streamlit run app.py
```

Register in the sidebar, log in, use the UI. First API call triggers
the cold-start spinner (~30 s if the Render instance is cold).

### B. Full stack locally via Docker Compose (API + Postgres)

```bash
cp .env.example .env          # set JWT_SECRET
make compose-up               # API on :5000, Postgres on the compose network
make smoke                    # curl /health, asserts 200
# in a second shell:
export API_BASE_URL=http://localhost:5000
streamlit run app.py
make compose-down             # teardown; add -v to wipe the postgres volume
```

The compose file mirrors the Render topology: depends_on uses a
healthcheck-gated Postgres so migrations can't fire before the DB is
ready.

### C. API without Docker (SQLite, Flask dev server)

```bash
pip install -r requirements.txt
cp .env.example .env
APP_ENV=dev alembic upgrade head        # create schema in skill-bridge-dev.db
python -m scripts.seed_db               # load jobs catalog from data/jobs.json
python run.py                           # Flask dev server on :5000
```

### D. Offline Streamlit demo (no API, no DB)

```bash
SKILL_BRIDGE_OFFLINE=1 streamlit run app.py
```

Falls back to direct-import core modules via eight 2-line shim files at
the repo root. In-memory storage, no login required. Useful for a
laptop demo when no backend is available.

## Configuration

All config is env-var driven; `app/config.py` routes through
`APP_ENV ∈ {dev, test, prod}`.

| Var | Required in | Default | Notes |
|---|---|---|---|
| `APP_ENV` | — | `dev` | Selects the config class |
| `DATABASE_URL` | prod | SQLite file in dev | Bare `postgresql://` URLs are rewritten to `postgresql+psycopg://` — see ADR-007 |
| `REPO_BACKEND` | — | auto | Force `memory` even with a `DATABASE_URL` in scope (benchmarks, tests) |
| `JWT_SECRET` | **prod** | dev literal | `init_extensions` raises `RuntimeError` in prod if empty |
| `ACCESS_TTL_SECONDS` | — | 900 | Access token lifetime |
| `REFRESH_TTL_SECONDS` | — | 1_209_600 | Refresh token lifetime |
| `ARGON2_TIME_COST` | — | 2 | See [OWASP guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html) |
| `ARGON2_MEMORY_COST` | — | 65536 (KiB) | |
| `ARGON2_PARALLELISM` | — | 4 | |
| `CORS_ORIGINS` | — | `""` prod / `"*"` dev | Empty disables CORS; CSV is exact-match allowlist |
| `GROQ_API_KEY` | — | unset | Unset → rule-based `FallbackCategorizer` |
| `API_BASE_URL` | Streamlit | `http://localhost:5000` | Client URL ladder: ctor arg → `st.secrets` → env → default |
| `SKILL_BRIDGE_OFFLINE` | — | `0` | `1` flips `app.py` to offline mode |

## Quality gate

```bash
make check     # ruff + ruff-format-check + mypy strict + pytest (with 80% coverage floor)
make hooks     # pre-commit install (fast subset runs on every commit)
```

`make check` mirrors CI exactly. A green local run predicts a green CI
run. See [ADR-018](decisions/ADR-018-tooling-choices.md) for tooling
rationale.

## API reference

Full endpoint documentation with curl recipes: [`API.md`](API.md).

Error envelope (every 4xx / 5xx):

```json
{ "error": { "code": "STRING_ID", "message": "...", "details": { "..." } } }
```

Correlation IDs: every response carries `X-Correlation-ID`; the server
reuses an inbound one or generates `uuid4().hex`. `grep cid=<id>` on
the structured JSON logs traces a single request end to end.

## Known limitations

- **Render free-tier cold start.** First request after ~15 min idle
  takes up to 30 s. The client's `warmup()` method covers this with
  a lazy spinner on the first call per session.
- **Single-worker gunicorn.** Rate-limit counters are in-memory per
  process. Multi-worker would multiply effective quotas by worker
  count. Fix is a Redis `storage_uri` one-liner (ADR-016).
- **Access tokens can't be revoked mid-TTL.** Logged-out users hold a
  working access token for up to 15 minutes. Fix needs a `jti`
  denylist (ADR-013).
- **`/auth/register` leaks email existence via 409.** Closing this
  needs an email-verification flow, out of Phase 3 scope (ADR-015).
- **No `GET /api/v1/profiles` endpoint.** After logout + re-login the
  Streamlit UI doesn't auto-reload the user's existing profile. Scoped
  as a Phase 6.1 candidate.

Debugging, failure modes, and recovery runbooks:
[`OPERATIONS.md`](../OPERATIONS.md).

## Evolution

The project was built in six self-contained phases. Each phase shipped
as a formal spec (requirements → design → tasks) under `.kiro/specs/`,
one or more ADRs in `decisions/`, and a tag (`v0.1.0` through `v0.6.0`).

| Phase | Tag | Scope | Tests |
|---|---|---|---|
| 1 — [REST API foundation](../.kiro/specs/phase-1-rest-api/) | v0.1.0 | Flask app factory, 12 endpoints, Pydantic v2, in-memory repos behind `typing.Protocol`, correlation IDs | 89 |
| 2 — [Persistence](../.kiro/specs/phase-2-persistence/) | v0.2.0 | SQLAlchemy 2.x, Alembic, dual-backend repos, idempotent seed, JSONB portability | 157 |
| 3 — [Auth](../.kiro/specs/phase-3-auth/) | v0.3.0 | Argon2id, JWT access + rotating refresh, multi-tenant `*_for_user` repos, rate limits, CORS | 268 |
| 4 — [Testing & Quality](../.kiro/specs/phase-4-testing-quality/) | v0.4.0 | Ruff, mypy strict, pytest-cov 80% floor, factory-boy, pre-commit, GitHub Actions | 274 |
| 5 — [Docker, CI/CD, Deploy](../.kiro/specs/phase-5-deploy/) | v0.5.0 | Multi-stage Dockerfile, docker-compose, GHCR publish, Render blueprint, live URL | 274 |
| 6 — [Streamlit integration](../.kiro/specs/phase-6-streamlit-integration/) | v0.6.0 | `api_client.py`, reactive refresh, cold-start warmup, two-mode `app.py`, auth sidebar | 337 |

The phase story and the cross-cutting decisions that tie them together
are in [`DESIGN_DOCUMENT.md`](../DESIGN_DOCUMENT.md). If you're here
for interview prep, see [`teaching.md`](../teaching.md).

## Repo map

```
skill-bridge/
├── app/                       Flask API (Phases 1–4)
│   ├── api/v1/                blueprints per resource
│   ├── auth/                  hashing, tokens, decorators
│   ├── core/                  domain logic (gap, roadmap, AI)
│   ├── db/                    ORM models, engine, session
│   └── repositories/          Protocol interfaces + impls
├── app.py                     Streamlit UI (two-mode since Phase 6)
├── api_client.py              HTTP client for the REST API (Phase 6)
├── migrations/                Alembic migrations
├── scripts/seed_db.py         idempotent jobs catalog loader
├── decisions/                 ADR-001 through ADR-020
├── tests/{unit,integration,properties}/
├── Dockerfile, docker-compose.yml, render.yaml
├── entrypoint.sh              migrations + seed + exec gunicorn
├── Makefile                   make check is the quality gate
└── .github/workflows/         ci.yml + build-and-publish.yml
```

## License

MIT. Data under `data/` is synthetic — no real PII.
