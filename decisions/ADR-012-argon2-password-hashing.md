# ADR-012: Argon2id password hashing via argon2-cffi

- **Status:** Accepted
- **Date:** 2026-04-30
- **Phase:** 3 — Authentication

## Context

Password hashing had three realistic options:

1. **bcrypt** (via `bcrypt` or `passlib`) — the classic choice. Salted,
   adaptive, but tops out at 72-byte passwords (silently truncates)
   and has no memory-hardness parameter.
2. **scrypt** — memory-hard, but the cost-parameter surface is more
   awkward and Python library support is thinner.
3. **Argon2id** — 2015 Password Hashing Competition winner.
   Memory-hard by design, three tunable knobs (time, memory,
   parallelism), OWASP's current recommendation.

## Decision

**Argon2id via `argon2-cffi`.**

- Wrapped in `app.auth.hashing.Argon2Hasher`, constructed once per
  Flask app in `init_extensions`. Cost parameters come from config
  (`ARGON2_TIME_COST=2`, `ARGON2_MEMORY_COST=65536` KiB,
  `ARGON2_PARALLELISM=4` by default).
- `TestConfig` dials those down to 1 / 8 KiB / 1 so the test suite —
  including Hypothesis property tests that hash repeatedly — stays
  under a few seconds. Weakened params are documented as
  test-only in the config module.
- `verify` swallows three exception families internally:
  `VerifyMismatchError` (wrong password), `VerificationError` (a
  catch-all), and `InvalidHashError` (malformed stored hash — descends
  from `ValueError`, NOT from `VerificationError`, so it has to be
  listed explicitly in the except tuple). No argon2 exception leaks
  past the hasher boundary; the handler layer gets a clean `bool`.
- `dummy_hash` property is a valid argon2id hash at the same cost
  parameters, pre-computed once at construction. The login handler
  calls `hasher.verify(hasher.dummy_hash, attempted_password)` on the
  unknown-email branch so the total CPU time of "user missing" and
  "wrong password" is indistinguishable. Closes the account-enumeration
  timing side channel (R2.4).

## Consequences

**Easier:**

- Memory-hard hash function is GPU-resistant out of the box — an
  attacker with a rack of GPUs gets much less speedup than they would
  against bcrypt.
- Cost parameters are config-driven, so a future "harden for prod"
  bump is a one-line env change rather than a code rewrite.

**Harder:**

- Argon2 is noticeably slower than bcrypt at production cost
  parameters (~50ms for a single hash vs ~10ms). That cost is paid
  on every login and every register. Acceptable at Phase 3's scale;
  a 500ms login response is better than a cheap-to-crack hash.
- The dummy-hash computation at Extensions init time adds ~50ms per
  `create_app` call. Tests notice (hence the weakened params).

**Constrained:**

- Never log a `password_hash` value. The hash format is reversible in
  the sense that an attacker with the hash can try passwords offline;
  it's not a JWT. Log entries that include user rows must project out
  the hash column.
