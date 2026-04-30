# ADR-013: HS256 JWTs, stateless access, stateful rotating refresh

- **Status:** Accepted
- **Date:** 2026-04-30
- **Phase:** 3 — Authentication

## Context

A token-based auth design has three main knobs:

1. **Signing algorithm** — HS256 (shared secret) vs RS256/ES256
   (asymmetric).
2. **Access-token state** — stateless (no server-side row) vs
   stateful (looked up in a denylist or table on every request).
3. **Refresh strategy** — long-lived single-use, rotation
   (new refresh on every /refresh call), or no refresh at all
   (re-login every 15 min).

## Decision

- **HS256** with a per-environment secret (`JWT_SECRET`).
- **Stateless access tokens** (15-minute TTL). No row, no lookup
  on the hot path — the decoder verifies signature + `exp` + `type`
  claim + loads the user, nothing else.
- **Stateful, rotating refresh tokens** (14-day TTL). Each refresh
  has a row in the `refresh_tokens` table keyed by `jti`. Calling
  `/auth/refresh` revokes the presented token (sets `revoked_at`)
  and issues a fresh pair. Presenting an already-revoked or
  unknown `jti` returns 401 `TOKEN_INVALID`.

## Consequences

**Easier:**

- HS256 is the simplest symmetric JWT scheme — no key-pair
  generation, no public-key distribution. Fine for a single-service
  deployment.
- Stateless access means zero DB lookups for the access-token
  validation path (past the user resolve) — 15 minutes of DB-free
  read traffic between refreshes.
- Rotation detects refresh-token theft in a bounded way: if an
  attacker and the real user both hold the same refresh, whichever
  one uses it second gets 401. The real user sees the failure and
  knows to re-authenticate.

**Harder:**

- Access tokens can't be revoked mid-TTL. A user who "logs out"
  still has a working access token for up to 15 minutes. This is
  documented in the API and in test_auth_logout.py
  (R4.5). A Redis-backed access-token denylist is a future option
  but explicitly out of Phase 3 scope.
- Rotating the shared secret invalidates every existing token.
  That's the same tradeoff any HS256 system makes; a graceful
  rotation (dual-secret, kid header) is Phase 5+ work.

**Constrained:**

- Splitting the API into multiple services in Phase 5+ would
  require either sharing `JWT_SECRET` across services (risky — any
  compromised service compromises all) or migrating to RS256
  (public key for verifiers, private key only on the auth service).
  The `tokens.py` module is small enough to swap in place.
- `ProdConfig` has no default `JWT_SECRET`. `init_extensions`
  raises `RuntimeError` at create_app time if prod is booted
  without one. Fails loud at deploy rather than at first login.
