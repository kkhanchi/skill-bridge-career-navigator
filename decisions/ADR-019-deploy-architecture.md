# ADR-019: Phase 5 deploy architecture — Docker, GHCR, Render

- **Status:** Accepted
- **Date:** 2026-04-30
- **Phase:** 5 — Docker, CI/CD, Deployment

## Context

Phase 5 takes the application from "green CI on a feature branch" to
"a public URL hiring managers can click." The shape of that work
forces ten distinct decisions, consolidated here as one ADR because
they form a coherent packaging-and-deploy stack.

## Decision

### 1. Multi-stage Dockerfile over single-stage

A single-stage image that `pip install`s from `python:3.12-slim`
carries ~200 MB of build-time cruft: `pip`, `setuptools`, gcc (if
any dep needs it). Multi-stage isolates that into a `builder`
stage and copies only the installed packages into the `runtime`
stage. Expected image size ~215 MB (ADR-019's design budget is
< 250 MB).

### 2. `python:3.12-slim` over alpine

Alpine's musl libc is smaller but known to trip up packages with
C extensions. `argon2-cffi` and `psycopg` are both in play; both
ship prebuilt manylinux wheels that target glibc. Switching to
alpine would force source builds of these wheels on every CI run.
Slim is ~130 MB base vs alpine's ~45 MB — the delta doesn't
justify the compatibility risk.

### 3. Non-root UID 10001

Defense in depth. If the container is compromised, the attacker
starts as user 10001 (a system user with no home dir write
permissions outside `/home/skillbridge`), not root. The UID is
fixed so any future volume mount has predictable ownership.

### 4. `--workers 1` in gunicorn

ADR-016 documented that the in-memory rate limiter uses per-worker
counters — multi-worker deployments effectively multiply the quota
by N. On Render's free tier we stay at a single worker. A future
phase swapping to Redis-backed rate limiting (`storage_uri="redis://..."`
— one-line config change) relaxes this.

### 5. GHCR over Docker Hub

GitHub Container Registry:
- Free for public repos (Docker Hub has pull-rate limits that
  sometimes trip CI).
- Auth via `GITHUB_TOKEN` — no separate account, no PAT rotation.
- Integrated with the GitHub Packages UI next to the repo.
- Native support for OCI labels (source, revision, license) that
  surface in the GHCR web UI.

Docker Hub remains a reasonable alternative but requires an
independent account + secret management.

### 6. Render over Railway / Fly.io

- **Free-tier Postgres add-on**: Render includes a managed Postgres
  in the free tier. Railway recently scaled back free Postgres.
  Fly.io requires running your own Postgres cluster. For a portfolio
  project where operating the DB is out of scope, Render wins.
- **Blueprint model (`render.yaml`)**: declarative config in version
  control; same philosophy as `pyproject.toml` over per-command flags.
  Railway has an equivalent (`railway.toml`) but Render's docs are
  more mature.
- **Docker-native**: Render builds images from your Dockerfile
  directly. No Buildpack layer, no opinionated framework detection.
  What you dockerize locally is what ships.

### 7. Declarative `render.yaml` over dashboard config

The service config lives in git next to the code that depends on
it. A wipe-and-restore produces the same service. Dashboard-only
config invites drift.

### 8. `preDeployCommand: alembic upgrade head`

Render runs the pre-deploy command before swapping the new
container in. If the migration fails, the deploy aborts and the
old container keeps serving traffic. Fail-closed semantics —
a bad migration can't take the service down because the healthy
container stays up.

Running migrations inside the container's `entrypoint.sh`
(instead of as a separate Render pre-deploy step) would also
work, BUT: every container start would re-run the check, which
is wasted CPU on warm restarts. Pre-deploy runs once per deploy.
Both patterns are safe because `alembic upgrade head` is
idempotent (Phase 2 R1.6 property). Using both is belt-and-
suspenders: entrypoint.sh covers local compose and manual
`docker run`, render.yaml covers production.

### 9. stdout / stderr logs over an observability stack

Gunicorn's `--access-logfile -` and `--error-logfile -` route both
streams to stdout/stderr. Render's log ingestion captures them and
presents them in the dashboard. Phase 1's structured JSON log
format (correlation IDs, fields) survives the pipeline intact.

Prometheus metrics, Grafana dashboards, and a proper error-tracking
sink (Sentry / similar) are explicitly out of Phase 5 scope —
they're a bonus-depth phase candidate.

### 10. `/health` stays database-independent

Render's health probe runs every ~30 s. If `/health` queried the DB,
every transient DB blip (slow query, connection reset, pool
exhaustion) would mark the container unhealthy and trigger a
restart. That's worse than serving a few 500 errors for the
duration of the blip.

The DB is reachable → process is alive → process can serve most
endpoints. `/health` only asserts the last of those; the first
two are the DB's and Render's problems, respectively.

## Consequences

**Easier:**

- One command (`docker compose up`) reproduces the production
  topology locally. Bugs that only manifest in the deployed
  environment become rare.
- `render.yaml` + the two GitHub Actions workflows give a fully
  declarative deploy pipeline: every decision lives in version
  control.
- GHCR images are reusable. Any future Kubernetes / Docker Swarm /
  other-PaaS experiment pulls the same image without rebuilding.
- The Phase 4 quality gate is non-negotiable — the publish
  workflow blocks on `ci.yml` passing, so no image ever ships
  from a red CI.

**Harder:**

- Free-tier cold starts: Render spins down idle services after
  ~15 min of inactivity. First request after a cold stop takes
  ~30 s. Documented in README; real users would pay for the
  paid tier which keeps services warm.
- Multi-worker is off. Rate limits are per-process; anyone
  running this behind a proxy with multiple replicas needs the
  Redis-backed limiter swap first.
- Two CI workflows to maintain (`ci.yml` + `build-and-publish.yml`).
  Combining them into one is tempting but would couple quality-gate
  latency to image-push latency, making the green-checkmark signal
  noisier.

**Constrained:**

- The `render.yaml` blueprint is the source of truth for prod
  config. Manual dashboard changes that aren't mirrored in the
  blueprint drift silently — any dashboard change should be
  back-ported to the file on the same PR.
- Migrations MUST stay idempotent. A migration that assumes a
  starting state ("rename column X" without a guard for "already
  renamed") would fail on the second deploy. Phase 2's round-trip
  smoke test asserts this for the existing migrations; new
  migrations must pass the same check.
- Base image updates (`python:3.12-slim` → `python:3.13-slim`)
  require re-running the full CI + publish pipeline and a Render
  redeploy. That's the right amount of ceremony for a base image
  swap; we don't need to optimise it.

## Alternatives considered and rejected

- **Single-stage Dockerfile**: image too large (~400 MB); ships
  build tooling to prod unnecessarily.
- **Alpine base**: C extension compatibility friction.
- **Docker Hub**: pull-rate limits, separate account.
- **Railway**: Postgres free-tier story weaker.
- **Fly.io**: self-managed Postgres is out of Phase 5 scope.
- **Heroku**: paid-only since 2022; free tier gone.
- **Terraform / Pulumi for the Render service**: overkill for one
  web service + one DB; `render.yaml` is the Render-native IaC.
- **Buildpacks**: Render supports them but they add an opinionated
  layer between your requirements.txt and the final image. Docker
  is more transparent and forces us to think about the image
  surface explicitly.
- **Combining `ci.yml` and `build-and-publish.yml`**: couples
  concerns; the split cleanly separates quality gate from
  publish.

## Future work (noted, not scoped)

- Redis-backed flask-limiter (Phase 5+ or a bonus phase) — removes
  the `-w 1` constraint.
- Custom domain + Cloudflare / similar in front — post-portfolio.
- Prometheus + Grafana — a bonus observability phase.
- Sentry / error tracking sink — same.
- PR-preview deploys on Render — free tier doesn't include
  per-PR databases, so deferred.
