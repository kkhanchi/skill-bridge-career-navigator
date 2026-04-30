"""HTTP client for the SkillBridge REST API.

Wraps :mod:`requests` with the behaviours Phase 6 needs to drive the
Streamlit UI against the Phase 5 deployed backend:

- **16 endpoint methods** — one per Phase 1–3 endpoint (auth, jobs,
  resume, profiles, analyses, roadmaps). See R2.1–R2.16.
- **Reactive token refresh** — a 401 on an authenticated call triggers
  exactly one ``POST /api/v1/auth/refresh`` and one retry; a second
  401 raises :class:`AuthExpiredError`. Bounded at 3 HTTP requests per
  authenticated method call (R3, property P1).
- **Cold-start warmup** — the first call of a session pings ``/health``
  with exponential backoff (1s, 2s, 4s, 8s, 16s; max 6 attempts;
  ~35 s total) before the real request. Render's free tier spins
  down after 15 min idle (R4, ADR-019).
- **5-leaf error taxonomy** — every HTTP / transport failure surfaces
  as one of :class:`ApiClientError`, :class:`ApiServerError`,
  :class:`ApiConnectionError`, :class:`AuthExpiredError`, or
  :class:`RateLimitedError`. All inherit :class:`ApiError` for single
  ``except`` catches at the Streamlit layer (R7).

Design reference: ``.kiro/specs/phase-6-streamlit-integration/design.md``.

The client is deliberately Streamlit-agnostic. It does not read or
write ``st.session_state``; the caller (``app.py``) passes tokens via
:meth:`ApiClient.set_tokens` and reads mutated tokens back via
:attr:`ApiClient.tokens`. That keeps the module unit-testable with
``responses`` under plain ``pytest`` (R1.6).
"""

from __future__ import annotations

from typing import Any

import requests

__all__ = [
    "ApiClient",
    "ApiError",
    "ApiClientError",
    "ApiConnectionError",
    "ApiServerError",
    "AuthExpiredError",
    "RateLimitedError",
]


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


class ApiError(Exception):
    """Base class for every exception raised by :class:`ApiClient`.

    Catch this at the Streamlit boundary when you want to handle any
    client failure uniformly. More specific subclasses carry structured
    fields (status code, server error envelope, retry_after, etc.) for
    targeted UX per R7.7.
    """


class ApiConnectionError(ApiError):
    """Network / DNS / timeout / TLS failure.

    Wraps the underlying ``requests.RequestException`` so callers can
    inspect the original cause without re-raising through layers.
    Raised on any ``requests.ConnectionError``, ``requests.Timeout``, or
    any other ``requests.RequestException`` per R7.5.
    """

    def __init__(self, original: Exception) -> None:
        super().__init__(str(original))
        self.original = original


class ApiClientError(ApiError):
    """HTTP 4xx other than 401 (auth-handled) and 429 (rate-limit-handled).

    Carries the server's ``error`` envelope (``code`` + ``message``)
    so the UI can render the message verbatim per R7.7 and tests can
    assert on the machine-readable ``code``. A 400 VALIDATION_FAILED
    on a profile create lands here, as does a 409 EMAIL_TAKEN on
    register and a 404 NOT_FOUND on a GET by id.

    Raised per R7.3.
    """

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class ApiServerError(ApiError):
    """HTTP 5xx.

    The client never retries 5xx — retry is the UI layer's choice, and
    only :meth:`ApiClient.warmup` loops. Body is captured for
    diagnostics but truncated to 500 chars so we don't stash HTML pages
    or stack traces in exception state.

    Raised per R7.4.
    """

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status
        self.body = body


class AuthExpiredError(ApiError):
    """Raised after :attr:`ApiClient`'s reactive-refresh path is exhausted.

    Signals one of three terminal auth states (R3.3):

    - The refresh call itself returned 401 (refresh token revoked /
      expired).
    - The retry of the original request returned 401 (new access
      token didn't help — token was revoked, user was deleted, etc.).
    - No refresh token was stored when a 401 arrived (caller never
      logged in, or we already cleared tokens on a prior
      ``AuthExpiredError``).

    The client has already cleared its stored tokens by the time this
    is raised. The UI should mirror that into ``st.session_state`` and
    rerun into the login sidebar per R7.7.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class RateLimitedError(ApiError):
    """HTTP 429.

    Split out from :class:`ApiClientError` because the UI needs the
    ``Retry-After`` header to render a countdown (Phase 3 auth
    endpoints are rate-limited at 5/min per ADR-017 and the UI wants
    to surface the exact retry window). ``retry_after`` is ``None``
    if the header is missing or unparseable.

    Raised per R7.2.
    """

    def __init__(self, message: str, retry_after: int | None) -> None:
        super().__init__(message)
        self.message = message
        self.retry_after = retry_after


# ---------------------------------------------------------------------------
# ApiClient skeleton
# ---------------------------------------------------------------------------


class ApiClient:
    """HTTP client for the SkillBridge REST API.

    Stage A ships this class as a skeleton: all method signatures are
    in place and raise :class:`NotImplementedError` so the typed call
    sites in ``app.py`` can compile, but no method has behaviour yet.
    Stages B and C fill in the internals and the 16 public endpoints.

    The class deliberately does not import or reference ``streamlit``
    at module load — ``_resolve_base_url`` does an optional import
    inside a ``try`` so this module can be imported in plain pytest
    runs without a Streamlit runtime (R1.3, R1.6).

    Attributes:
        _base_url: The resolved API root. No trailing slash.
        _session: A long-lived :class:`requests.Session` for
            connection reuse across requests. Survives Streamlit
            reruns because the ``ApiClient`` instance is pinned in
            ``st.session_state["api_client"]`` (design §Request
            lifecycle).
        _access: Current access token or ``None``.
        _refresh: Current refresh token or ``None``.
        _warm: ``True`` once :meth:`warmup` has seen a 200 from
            ``/health``. Never flips back to ``False`` within a single
            client lifetime.
        _default_timeout: Per-request timeout in seconds, overridable
            per call via the ``timeout`` kwarg.
    """

    def __init__(self, base_url: str | None = None) -> None:
        """Construct a client against ``base_url`` or the resolved default.

        Args:
            base_url: Explicit root URL. If omitted, resolves in the
                order specified by R1.4: ``st.secrets["API_BASE_URL"]``
                → ``os.environ["API_BASE_URL"]`` →
                ``"http://localhost:5000"``.
        """
        # Stage A stores nothing; Stage B fills in construction.
        raise NotImplementedError("ApiClient.__init__ — Stage B")

    def set_tokens(self, access: str | None, refresh: str | None) -> None:
        """Replace the client's stored access / refresh token pair.

        Called by ``app.py`` at the top of every Streamlit rerun to
        re-attach tokens from ``st.session_state``. The tokens may
        have been mutated by a login, logout, or reactive refresh in
        the previous rerun, and the client instance needs to observe
        that change.
        """
        raise NotImplementedError("ApiClient.set_tokens — Stage B")

    @property
    def tokens(self) -> tuple[str | None, str | None]:
        """Return ``(access, refresh)`` as currently stored.

        ``app.py`` reads this after any call that could rotate
        tokens (login, register, refresh, logout, any authed call
        that triggered a reactive refresh) and writes the pair back
        to ``st.session_state``.
        """
        raise NotImplementedError("ApiClient.tokens — Stage B")

    # ---------------------------------------------------------------
    # Cold-start warmup (R4)
    # ---------------------------------------------------------------

    def warmup(self, timeout: float = 35.0) -> None:
        """Poll ``/health`` with exponential backoff until 200 or exhaust.

        Backoff schedule: 1 s, 2 s, 4 s, 8 s, 16 s between attempts;
        max 6 attempts; cumulative cap ``timeout`` seconds (R4.1).
        On success sets ``self._warm = True``. On exhaust raises
        :class:`ApiConnectionError` — the caller renders R4.3's
        "Can't reach the API right now…" message and retries on the
        next interaction.

        Does NOT call :meth:`_ensure_warm` (would recurse).
        """
        raise NotImplementedError("ApiClient.warmup — Stage B")

    # ---------------------------------------------------------------
    # Auth endpoints (R2.1–R2.5)
    # ---------------------------------------------------------------

    def register(self, email: str, password: str) -> dict[str, Any]:
        """``POST /api/v1/auth/register`` (public). See R2.1."""
        raise NotImplementedError("ApiClient.register — Stage C")

    def login(self, email: str, password: str) -> dict[str, Any]:
        """``POST /api/v1/auth/login`` (public). See R2.2."""
        raise NotImplementedError("ApiClient.login — Stage C")

    def refresh(self) -> dict[str, Any]:
        """``POST /api/v1/auth/refresh`` using stored refresh token. See R2.3."""
        raise NotImplementedError("ApiClient.refresh — Stage C")

    def logout(self, timeout: float | None = None) -> None:
        """``POST /api/v1/auth/logout`` using stored refresh token.

        Best-effort server-side revocation. The UI's ``_handle_logout``
        clears local session state regardless of outcome (R5.7). The
        ``timeout`` kwarg exists so the UI can pass ``timeout=2.0`` to
        avoid a 10-second hang on a dead API (design §Error Handling
        / Network errors in logout). See R2.4.
        """
        raise NotImplementedError("ApiClient.logout — Stage C")

    def me(self) -> dict[str, Any]:
        """``GET /api/v1/auth/me`` (authed). See R2.5."""
        raise NotImplementedError("ApiClient.me — Stage C")

    # ---------------------------------------------------------------
    # Public reads (R2.6–R2.8)
    # ---------------------------------------------------------------

    def list_jobs(
        self,
        keyword: str | None = None,
        skill: str | None = None,
    ) -> dict[str, Any]:
        """``GET /api/v1/jobs`` with optional filters. See R2.6."""
        raise NotImplementedError("ApiClient.list_jobs — Stage C")

    def get_job(self, job_id: str) -> dict[str, Any]:
        """``GET /api/v1/jobs/{job_id}``. See R2.7."""
        raise NotImplementedError("ApiClient.get_job — Stage C")

    def parse_resume(self, text: str) -> dict[str, Any]:
        """``POST /api/v1/resume/parse`` (public). See R2.8."""
        raise NotImplementedError("ApiClient.parse_resume — Stage C")

    # ---------------------------------------------------------------
    # Profiles (R2.9–R2.12)
    # ---------------------------------------------------------------

    def create_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        """``POST /api/v1/profiles`` (authed). See R2.9."""
        raise NotImplementedError("ApiClient.create_profile — Stage C")

    def get_profile(self, profile_id: str) -> dict[str, Any]:
        """``GET /api/v1/profiles/{profile_id}`` (authed). See R2.10."""
        raise NotImplementedError("ApiClient.get_profile — Stage C")

    def update_profile(
        self,
        profile_id: str,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        """``PATCH /api/v1/profiles/{profile_id}`` (authed). See R2.11."""
        raise NotImplementedError("ApiClient.update_profile — Stage C")

    def delete_profile(self, profile_id: str) -> None:
        """``DELETE /api/v1/profiles/{profile_id}`` (authed, 204). See R2.12."""
        raise NotImplementedError("ApiClient.delete_profile — Stage C")

    # ---------------------------------------------------------------
    # Analyses (R2.13–R2.14)
    # ---------------------------------------------------------------

    def create_analysis(self, profile_id: str, job_id: str) -> dict[str, Any]:
        """``POST /api/v1/analyses`` (authed). See R2.13."""
        raise NotImplementedError("ApiClient.create_analysis — Stage C")

    def get_analysis(self, analysis_id: str) -> dict[str, Any]:
        """``GET /api/v1/analyses/{analysis_id}`` (authed). See R2.14."""
        raise NotImplementedError("ApiClient.get_analysis — Stage C")

    # ---------------------------------------------------------------
    # Roadmaps (R2.15–R2.16)
    # ---------------------------------------------------------------

    def create_roadmap(self, analysis_id: str) -> dict[str, Any]:
        """``POST /api/v1/roadmaps`` (authed). See R2.15."""
        raise NotImplementedError("ApiClient.create_roadmap — Stage C")

    def update_roadmap_resource(
        self,
        roadmap_id: str,
        resource_id: str,
        completed: bool,
    ) -> dict[str, Any]:
        """``PATCH /api/v1/roadmaps/{roadmap_id}/resources/{resource_id}``.

        Authed. See R2.16.
        """
        raise NotImplementedError("ApiClient.update_roadmap_resource — Stage C")

    # ---------------------------------------------------------------
    # Internals (Stage B)
    # ---------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        authed: bool,
        json: Any = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any] | None:
        """Single dispatch spine.

        Every public method funnels through here. Concentrates warmup
        triggering, auth header attachment, error mapping, and
        reactive-refresh-with-retry in one place so the
        "at most 3 HTTP requests per authenticated call" bound (R3.5,
        property P1) is a local invariant.
        """
        raise NotImplementedError("ApiClient._request — Stage B")

    def _do_request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        json: Any,
        params: dict[str, Any] | None,
        timeout: float,
    ) -> requests.Response:
        """The one-and-only call site for ``session.request``.

        Every outgoing HTTP call (real endpoint requests, warmup pings,
        refresh calls) goes through this. Maps
        :class:`requests.RequestException` → :class:`ApiConnectionError`
        (R7.5) in exactly one place.
        """
        raise NotImplementedError("ApiClient._do_request — Stage B")

    def _handle_response(
        self,
        resp: requests.Response,
    ) -> dict[str, Any] | None:
        """Map a :class:`requests.Response` to a body or an exception.

        - 2xx: returns ``resp.json()`` or ``None`` on 204 / empty body.
        - 429: raises :class:`RateLimitedError` with parsed
          ``Retry-After``.
        - 401 (public path): raises :class:`ApiClientError`. The
          authed path catches 401 before reaching here via the
          reactive-refresh branch in :meth:`_request`.
        - Other 4xx: raises :class:`ApiClientError(status, code,
          message)`.
        - 5xx: raises :class:`ApiServerError(status, body)` truncated
          to 500 chars.
        """
        raise NotImplementedError("ApiClient._handle_response — Stage B")

    def _parse_error_body(
        self,
        resp: requests.Response,
    ) -> tuple[str, str]:
        """Extract ``(code, message)`` from a server error envelope.

        Server responses on the happy error path look like
        ``{"error": {"code": "...", "message": "..."}}``. Render's
        503 cold-start page is HTML; proxies can inject anything.
        Falls back to ``("UNKNOWN", (resp.text or f"HTTP {status}")
        [:200])``. Never raises.
        """
        raise NotImplementedError("ApiClient._parse_error_body — Stage B")

    def _ensure_warm(self) -> None:
        """Run :meth:`warmup` lazily on the first public call of a session.

        Early-return if ``self._warm`` is already ``True``. Called
        from the top of :meth:`_request` so every public method
        triggers warmup exactly once per session regardless of path.
        """
        raise NotImplementedError("ApiClient._ensure_warm — Stage B")

    def _do_refresh(self) -> None:
        """Issue ``POST /api/v1/auth/refresh`` and update stored tokens.

        Called from :meth:`_request`'s reactive-refresh branch on a
        401 response. Uses :meth:`_do_request` directly (not
        :meth:`_request`) to bypass the warmup re-entry check — the
        caller is already inside :meth:`_request` and has satisfied
        ``_ensure_warm``.

        Raises :class:`ApiError` subclasses on failure; the caller
        catches that and raises :class:`AuthExpiredError` per R3.3.
        """
        raise NotImplementedError("ApiClient._do_refresh — Stage B")

    def _clear_tokens(self) -> None:
        """Set both stored tokens to ``None``.

        Called whenever reactive refresh proves the stored tokens are
        invalid (R3.3). The caller raises :class:`AuthExpiredError`
        after this runs; the UI then mirrors the clear into
        ``st.session_state``.
        """
        raise NotImplementedError("ApiClient._clear_tokens — Stage B")

    @staticmethod
    def _resolve_base_url(explicit: str | None) -> str:
        """Resolve the effective base URL per R1.4 / property P3.

        Order: explicit argument → ``st.secrets["API_BASE_URL"]`` →
        ``os.environ["API_BASE_URL"]`` → ``"http://localhost:5000"``.

        The ``streamlit`` import is wrapped in ``try/except Exception``
        so the client is import-safe outside a Streamlit runtime
        (pytest runs, offline CLI invocations). A missing streamlit
        module, a missing ``st.secrets`` attribute, or a missing
        ``API_BASE_URL`` key inside ``st.secrets`` all fall through to
        the env-var lookup.
        """
        raise NotImplementedError("ApiClient._resolve_base_url — Stage B")
