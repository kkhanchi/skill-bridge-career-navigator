# ADR-016: flask-limiter with in-memory storage (single-worker caveat)

- **Status:** Accepted
- **Date:** 2026-04-30
- **Phase:** 3 — Authentication

## Context

Rate limiting on auth endpoints is a Phase 3 requirement
(register 5/hour, login 10/minute, refresh 30/minute, all per IP).
The storage backend is a design knob:

1. **In-memory storage** (`memory://`). No external dependency.
   Counters are per-process.
2. **Redis** (`redis://host:port/db`). Shared across workers.
   Adds an infrastructure dependency.
3. **Database** (via flask-limiter's SQLAlchemy backend).
   Shares the PostgreSQL already in play for Phase 2. But every
   rate-limit check becomes a DB round-trip.

## Decision

**In-memory storage for Phase 3.**

- `Limiter(key_func=get_remote_address, storage_uri="memory://", ...)`
  attached per-app in `init_extensions`.
- `strategy="fixed-window"` — simple, predictable, same as the
  design spec's numeric budgets ("5/hour", not "5/1-hour-rolling").
- `headers_enabled=True` so clients get `X-RateLimit-*` headers
  on successful responses, useful for debugging.
- `default_limits=[]` — only endpoints with explicit
  `@limiter.limit(...)` are rate-limited. Resource endpoints stay
  uncapped so legitimate use of the API isn't throttled.

## Consequences

**Easier:**

- No external service needed for Phase 3. The in-memory strategy is
  correct for any deployment that runs a single worker (or a single
  process with many threads).
- Tests run fast — no Redis container, no ephemeral port juggling.
  Each test gets a fresh limiter because `create_app` builds a new
  per-app Limiter.

**Harder:**

- Multi-worker deployments effectively multiply the quota by the
  worker count. A 5/hour register limit with 4 gunicorn workers is
  "up to 20/hour across the fleet." Not a crippling leak for Phase 3
  (where the synthetic data + portfolio-scale traffic makes it
  immaterial), but it MUST be documented in the README and is
  called out in test_rate_limits.py.
- Replacing with Redis in Phase 5 is a one-line config change
  (`storage_uri="redis://..."`) — the limiter API doesn't change.

**Constrained:**

- The limit keys use `get_remote_address`, which resolves to the
  immediate connection peer. Behind a proxy (nginx, ALB), every
  request will look like it came from the proxy's IP — effectively
  collapsing all clients into one bucket. Any future reverse-proxy
  deployment will need `TRUSTED_PROXIES` configured and a custom
  `key_func` that reads `X-Forwarded-For`. Also documented.
- The test suite accepts multi-worker unsuitability. A
  `run_all_tests_in_parallel` path that spun up the same limit
  counter would produce non-deterministic test outcomes; keeping
  the limiter per-app-instance sidesteps that entirely.
