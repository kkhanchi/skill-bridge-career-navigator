# ADR-020: Streamlit Integration with the Deployed REST API

**Status:** Accepted
**Phase:** 6
**Date:** 2026-05-01

---

> **R9 Legacy_Shims disposition: Option B — keep shims, add `SKILL_BRIDGE_OFFLINE=1` env var.**
>
> The eight top-level shim modules (`ai_engine.py`, `gap_analyzer.py`,
> `job_catalog.py`, `profile_manager.py`, `profile_printer.py`,
> `resume_parser.py`, `roadmap_generator.py`, `models.py`) stay at the
> repo root. `app.py` checks `SKILL_BRIDGE_OFFLINE` at the very top
> and either imports the shims (offline mode) or the new
> `api_client.py` (online mode, default). Rejected options and
> rationale are recorded at the bottom of this ADR.

---

## Context

Phase 5 shipped a live REST API at
`https://skillbridge-api-4foe.onrender.com`. The Streamlit reference
UI was still running the Phase 0 direct-core-import flow from before
the API existed: every user session held an in-memory profile,
analyses and roadmaps were re-computed from local Python modules,
nothing persisted. The deployed API was dark traffic.

Phase 6 cuts the UI over to HTTP. This ADR records the
non-obvious design choices made during that cutover. Requirements
and design docs are at `.kiro/specs/phase-6-streamlit-integration/`.

## Decisions

### 1. Hand-rolled `requests` wrapper over an OpenAPI codegen client

We wrote `ApiClient` as a straight `requests.Session` wrapper with
16 methods, one per Phase 1–3 endpoint.

**Alternatives considered:**

- **openapi-generator-python** or similar codegen from an
  `openapi.yaml`. Would auto-generate a client with typed models,
  but the Flask API doesn't currently emit an OpenAPI schema. We'd
  have to generate the schema by hand or add a runtime spec
  generator (`apispec`, `flask-smorest`) — that's net *more*
  infrastructure for 16 methods.
- **httpx** over requests. Async-capable, but Streamlit's execution
  model is synchronous top-to-bottom on every rerun. Async bought
  us nothing.

Hand-rolled wins on maintenance budget: 16 methods × ~10 lines
each is less code than either a codegen pipeline or an async
migration. The whole client fits in one file and reads top-to-bottom.

### 2. Reactive token refresh on 401 (not proactive on `exp`)

The client only attempts a refresh when it sees an actual 401.
It does not decode the access token's `exp` claim and pre-emptively
refresh on "token about to expire."

**Why:**

- Decoding a JWT correctly client-side requires either PyJWT with
  the signing secret (the UI is never trusted with) or an unverified
  decode that reads `exp` blindly. Both are footguns.
- Reactive refresh costs one extra round-trip per expired-token
  call — affordable, and the Streamlit rerun is already pulling
  fresh data on every interaction.
- The 3-request bound (the original call + refresh + retry) is a
  local invariant of `ApiClient._request`, which is property P1's
  witness in the test suite.

### 3. Cold-start retry inside the client, not the UI

Render's free tier spins down after 15 min idle. The *first* API
call of a fresh session faces a ~30 s cold start. We handle this
by having `ApiClient` run `warmup()` lazily on the first public
method call; once warm, subsequent calls skip the retry path.

**Alternatives considered:**

- **UI-layer wrapper.** A `with_warmup()` helper in `app.py` that
  wraps client calls. Works, but every call site needs the wrapper
  or it's silent drift. Fewer points of failure to keep the logic
  in one place.
- **Always hit `/health` first.** Cheap but wasteful: every page
  reload after the app is warm burns a network round-trip for no
  gain. The `_warm` flag on the client short-circuits this.

### 4. Five-leaf error taxonomy with a shared base

`ApiError` at the root; leaves for `ApiClientError` (4xx non-401),
`ApiServerError` (5xx), `ApiConnectionError` (network), `AuthExpiredError`
(401 after refresh exhausted), and `RateLimitedError` (429).

**Why five:**

- Each one carries different structured fields the UI needs:
  - `ApiClientError` — status + machine-readable code + message.
  - `RateLimitedError` — parsed `Retry-After` for countdown UX.
  - `AuthExpiredError` — signals the UI should wipe session tokens.
  - `ApiServerError` — status + truncated body for diagnostics.
  - `ApiConnectionError` — wraps the original `requests` exception.
- All share `ApiError` so `except ApiError:` catches the family when
  the UI doesn't care about the specific branch.

R7 and R7.7 in the requirements map HTTP surface to exception type
to rendered UX, one-to-one.

### 5. `_parse_error_body` fallback for malformed envelopes

Render's 503 cold-start page is HTML. Misconfigured proxies inject
anything. The parser tries the Phase 1 envelope shape first; on any
failure returns `("UNKNOWN", resp.text[:200])`. Never raises.

**Why this matters:**

A JSON parse error while *building* an error message would silently
turn a server error into a client `ValueError`. The UI would see a
crash instead of a user-friendly message. The 200-char truncation
keeps exception state small — no HTML stack traces in traceback.

### 6. Rerun-model session-state reattachment

The `ApiClient` instance lives in `st.session_state["api_client"]`;
access and refresh tokens live under separate session keys.
`get_or_create_client()` creates-or-reuses the instance and re-attaches
the tokens at the top of every Streamlit rerun.

**Why separate keys:**

- Tokens can mutate between reruns: login, logout, reactive refresh.
- If tokens lived *inside* the client instance without a session-state
  mirror, the UI could commit a rotated refresh token to one rerun
  and lose it on the next because the client is the same pickled
  object Streamlit deserializes.
- Storing them in `st.session_state` with dedicated keys makes the
  contract explicit: every mutating call path ends with
  `_persist_tokens(client)` which mirrors `client.tokens` back.

### 7. Sidebar as in-file helper, not a separate module

`render_auth_sidebar` and its five helpers (`_render_logged_in`,
`_render_auth_forms`, `_login_form`, `_register_form`,
`_render_rate_limit`) live in `app.py`.

Streamlit apps of this size stay single-file by convention (see
Streamlit's own gallery). Splitting UI across modules fights the
rerun model — every widget's key has to be unique across the whole
module path, and cross-module import order matters at rerun time.
One file keeps the widget graph visible at a glance.

### 8. Logout uses a 2-second client-side timeout

`client.logout(timeout=2.0)` on the UI's logout handler. Best-effort
server-side revocation; local session state wipes regardless.

**Why 2 s:**

- The default 10 s timeout produces a visible hang in the UI when
  the API is down or slow.
- Logout is fundamentally idempotent — Phase 3's `/auth/logout`
  returns 204 even for malformed or already-revoked tokens.
- A 2 s window is enough for the happy path (sub-second in practice)
  without punishing the user on a cold API.

### 9. One property per distinct concern

Phase 6 ships four correctness properties:

- **P1** — Reactive refresh bounded (at most 3 HTTP calls).
- **P2** — Logout idempotency (session state absent after any N ≥ 1
  calls to the logout handler).
- **P3** — URL ladder deterministic (first non-None source wins).
- **P4** — Profile round-trip (client-side (de)serialisation is
  lossless).

None of the four is implied by another, and each validates a
distinct requirement cluster. Property tests live in
`tests/properties/test_api_client_properties.py`; P2 lives with
its handler in `tests/unit/test_api_client.py`.

### 10. No persistent token storage (no cookies, no localStorage)

Tokens live in `st.session_state` and die with the browser tab.

**Why:**

- Streamlit's built-in mechanism for cookie / localStorage access
  requires a custom component (non-trivial TS + npm build).
- Phase 6's scope was explicitly UI rewire, not adding a new
  persistence layer.
- The UX trade-off (log in again if you close the tab) is
  acceptable for a portfolio project. Phase 7 candidate if we
  revisit.

## Legacy_Shims disposition (R9)

Three options were considered:

- **Option A — Delete the shims.** `app.py` imports directly from
  `app.core.*` for the offline path. Smallest end-state surface.
  **Rejected** because it removes the zero-infra demo path. A
  reviewer cloning the repo and running `streamlit run app.py`
  with no API available would hit a crash instead of seeing the UI.
  The shims are 2-line re-exports per ADR-006 — deleting them saves
  nothing meaningful in maintenance.
- **Option B — Keep the shims; `SKILL_BRIDGE_OFFLINE=1` flips
  behaviour.** **Accepted.** The offline demo costs eight 2-line
  files and one env-var check in `app.py`. Portfolio value is high:
  someone can run the UI on a laptop with zero backend and see
  something working. ADR-006's "shims are a compatibility layer"
  rationale extends: Phase 6 is another consumer.
- **Option C — Move shims to `skill-bridge/legacy/`.** Survives the
  shims but segregates them. **Rejected** because it breaks every
  external script or notebook that `import profile_manager`s at
  the repo root, without buying us anything. Option B keeps the
  import surface stable; the "they look like legacy" signal is
  already in the docstrings.

## Consequences

Positive:

- The Streamlit UI exercises the deployed API, turning dark traffic
  into real usage against Phase 1–3 endpoints.
- Multi-user operation: each logged-in account has its own
  server-side profile / analyses / roadmaps, persisted across
  sessions.
- Offline demo path preserved at near-zero cost via `SKILL_BRIDGE_OFFLINE=1`.

Negative:

- Network round-trips add latency vs. direct function calls. Mitigated
  by Render's Oregon region + the warmup path; steady-state
  interactions are sub-500ms.
- Free-tier cold start is user-visible on the first request after
  ~15 min idle. Mitigated by the warmup spinner message.
- Tokens lost on tab close (by design — see Decision 10).

## References

- Requirements: `.kiro/specs/phase-6-streamlit-integration/requirements.md`
- Design: `.kiro/specs/phase-6-streamlit-integration/design.md`
- Tasks: `.kiro/specs/phase-6-streamlit-integration/tasks.md`
- Prior art: ADR-006 (shims pattern), ADR-013 (JWT secret), ADR-014
  (refresh rotation), ADR-017 (rate limits), ADR-019 (deploy
  architecture)
