# ADR-017: CORS allowlist via env var, prod requires explicit origins

- **Status:** Accepted
- **Date:** 2026-04-30
- **Phase:** 3 — Authentication

## Context

Browser clients calling the API from a different origin need the
server to emit the right CORS headers. Three policy knobs:

1. **What origins are allowed?** Wildcard, explicit list, or no CORS.
2. **Cookies vs Bearer tokens?** `supports_credentials=True` is
   required for cookies but is forbidden by browsers when combined
   with `Access-Control-Allow-Origin: *`.
3. **What headers are allowed?** At minimum `Authorization` (the
   Bearer token) and `Content-Type` (JSON).

## Decision

- **Allowlist via `CORS_ORIGINS` env var**, read per-config:
  - Empty string → no CORS headers emitted (prod default).
    Same-origin still works; cross-origin browsers reject.
  - `"*"` → allow any origin (dev default only).
  - Comma-separated list → exact-match allowlist.
- **`supports_credentials=False`.** We use Bearer tokens in the
  Authorization header, not cookies, so credentials mode isn't
  needed. This also sidesteps the browser restriction on combining
  `*` with credentials.
- **`allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"]`**
  so browser preflight `OPTIONS` requests don't strip our auth header
  or our custom correlation id.
- **`expose_headers=["X-Correlation-ID"]`** so browser JS can read
  the correlation id off the response and log it alongside client-
  side errors.
- **`max_age=600`** — caches preflight responses for 10 minutes.
- **`ProdConfig` has no `CORS_ORIGINS` default.** Operators MUST set
  the env var to enable CORS in prod. Omitting it silently disables
  CORS — a misconfigured deploy fails CLOSED (same-origin only),
  not OPEN (any origin).

## Consequences

**Easier:**

- Dev developers get `*` so a locally-running frontend on any port
  can call the API without setup friction.
- Production is safe-by-default: nothing served unless explicitly
  requested via env.
- The `allow_headers` list includes `X-Correlation-ID` so any
  client library that wants to thread a correlation id through its
  HTTP calls works without server changes.

**Harder:**

- Operators MUST remember to set `CORS_ORIGINS` when they want
  browser clients to work in prod. Documented in README. Misconfig
  produces "fetch blocked by CORS" errors in the browser console
  rather than a misleading 200; that's the failure mode we want.
- Single-origin → small allowlist → long allowlist migration
  requires a redeploy. Acceptable for Phase 3; not yet worth a
  dynamic origin store.

**Constrained:**

- Cookie-based session auth is ruled out by `supports_credentials=False`.
  If a Phase 5+ design decides to add a browser session cookie, the
  credentials flag would flip, and `*` would become illegal — the
  CORS helper would have to enforce the allowlist shape.
- The API doesn't emit `Vary: Origin` manually. flask-cors handles
  that automatically when a specific origin matches, but any caching
  layer between the API and the browser needs to understand the
  `Vary` header to avoid serving stale responses to the wrong origin.
