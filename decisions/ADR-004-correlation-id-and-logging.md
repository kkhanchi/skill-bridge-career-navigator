# ADR-004: Correlation ID propagation via flask.g + stdlib logging

- **Status:** Accepted
- **Date:** 2026-04-30
- **Phase:** 1 — REST API Foundation

## Context

Two cross-cutting concerns land together:

1. **Structured logging.** The API must emit JSON log lines with a
   base set of fields (`ts`, `level`, `logger`, `cid`, `msg`) plus
   optional per-event extras.
2. **Correlation IDs.** Every request must carry a unique id that
   flows into each of its log lines and back out as an
   `X-Correlation-ID` response header, so a reader of `grep cid
   <cid> logs.json` sees a full request trace.

Libraries considered:

- **structlog** — rich, context-binding logger with JSON formatting
  out of the box.
- **stdlib logging** + a custom `Formatter` + `Filter`.
- **loguru** — ergonomic but opinionated API.

Correlation-id storage options:

- `flask.g` — per-request, reset automatically between requests.
- `contextvars.ContextVar` — works inside and outside request scope.

## Decision

Use **stdlib `logging`** with:

- `JsonFormatter` (writes the five base fields + any
  `extra={"extra_fields": {...}}` payload).
- `CorrelationIdFilter` that reads `flask.g.correlation_id` when
  inside a request context and falls back to `"-"` otherwise
  (so startup/teardown logs still render correctly).
- Idempotent handler install so `create_app` can be called repeatedly
  in the test suite without piling up handlers.

Correlation ID lifecycle in `app/__init__.py`:

- `before_request` reads `X-Correlation-ID` from the inbound headers
  and reuses it, or generates `uuid4().hex` if absent.
- `after_request` echoes the id on every response (success and error)
  and logs `request.end` with `status` + `duration_ms`.

## Consequences

**Easier:**

- No new runtime dependency. `structlog` would be ~15 lines less code
  but adds a third-party import for what amounts to a formatter
  and a filter.
- Tests assert on log structure via `TestConfig`'s plain-text
  formatter, not JSON, so assertions stay human-readable.
- Migration path: if/when Observability (Bonus Phase Option C) adopts
  structlog, the handler install site in `app/utils/logging.py` is
  the only thing that changes.

**Harder:**

- Slightly more boilerplate than a structlog-based setup. Five files
  instead of two. This is paid once.

**Constrained:**

- Request bodies must never be logged (R7.6). The `request.start` /
  `request.end` hooks in the factory log only `method`, `path`,
  `status`, and `duration_ms`. New hooks that want to log extra
  fields go through `extra={"extra_fields": {...}}` — never raw
  payloads. This is a process convention enforced by code review.
- Inbound `X-Correlation-ID` headers are trusted verbatim (used as
  the id if present). For Phase 1 this is fine; if we ever expose
  the API to an untrusted caller that could use this to poison logs,
  we add validation at the `before_request` hook.
