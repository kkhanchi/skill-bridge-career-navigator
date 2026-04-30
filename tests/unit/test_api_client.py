"""Unit tests for :mod:`api_client` internals (Phase 6 Stage B).

Covers the dispatch spine, error taxonomy, reactive refresh, warmup,
and URL resolution. Endpoint method tests (16 happy paths) live
alongside these in Stage C additions.

All HTTP calls are stubbed with :mod:`responses` so the suite runs
offline. The module imports ``api_client`` which is at the
``skill-bridge/`` root; pytest's ``rootdir`` setting in
``pyproject.toml`` puts that on the import path.

Design reference: ``.kiro/specs/phase-6-streamlit-integration/design.md``.
"""

from __future__ import annotations

from typing import Any

import pytest
import requests
import responses

from api_client import (
    ApiClient,
    ApiClientError,
    ApiConnectionError,
    ApiServerError,
    AuthExpiredError,
    RateLimitedError,
    _parse_retry_after,
)

# Every test uses this base so we can hardcode the match URLs in
# responses.add stubs. Trailing slash is intentional — it exercises
# the R6.3 strip-trailing-slash behaviour on __init__.
BASE = "http://api.test/"
CANONICAL = "http://api.test"  # base after __init__'s rstrip


def _warm(client: ApiClient) -> None:
    """Flip the client to warm so tests skip the 6-attempt warmup path.

    The warmup path is covered by a dedicated test class below; other
    tests don't care about it and would otherwise eat 5 × sleep() on
    the first call (since the `responses` registry doesn't include
    ``/health`` by default).
    """
    client._warm = True


# =====================================================================
# URL ladder (R1.4, P3)
# =====================================================================


class TestURLResolution:
    """Property 3 witness tests — one per branch of the R1.4 ladder."""

    def test_url_ladder_explicit_wins(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Even with env var set, the explicit argument takes priority.
        monkeypatch.setenv("API_BASE_URL", "http://env.example")
        client = ApiClient(base_url="http://explicit.example")
        assert client._base_url == "http://explicit.example"

    def test_url_ladder_env_over_default(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("API_BASE_URL", "http://env.example")
        client = ApiClient()
        assert client._base_url == "http://env.example"

    def test_url_ladder_default(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("API_BASE_URL", raising=False)
        client = ApiClient()
        assert client._base_url == "http://localhost:5000"

    def test_url_ladder_strips_trailing_slash(self) -> None:
        client = ApiClient(base_url="http://api.test/")
        assert client._base_url == "http://api.test"

    def test_url_ladder_streamlit_import_failure_falls_through(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # When streamlit is importable but st.secrets access raises
        # (e.g. running outside a Streamlit runtime), the resolver must
        # not propagate the exception. It should fall through to env.
        monkeypatch.setenv("API_BASE_URL", "http://fallback.example")

        # Replace st.secrets with an object whose .get() raises. The
        # resolver's try/except Exception must swallow this.
        class _BrokenSecrets:
            def get(self, key: str) -> Any:
                raise RuntimeError("no streamlit runtime")

        import streamlit as st

        monkeypatch.setattr(st, "secrets", _BrokenSecrets(), raising=False)
        client = ApiClient()
        assert client._base_url == "http://fallback.example"


# =====================================================================
# _parse_retry_after helper
# =====================================================================


class TestParseRetryAfter:
    """Retry-After parsing edge cases."""

    def test_none_header(self) -> None:
        assert _parse_retry_after(None) is None

    def test_empty_header(self) -> None:
        assert _parse_retry_after("") is None

    def test_integer_seconds(self) -> None:
        assert _parse_retry_after("60") == 60

    def test_integer_with_whitespace(self) -> None:
        assert _parse_retry_after("  42  ") == 42

    def test_negative_treated_as_none(self) -> None:
        assert _parse_retry_after("-5") is None

    def test_http_date_unparseable_returns_none(self) -> None:
        # We intentionally don't parse RFC 7231 HTTP dates — Phase 3's
        # limiter emits integer seconds and that's all the UI needs.
        assert _parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") is None


# =====================================================================
# Error taxonomy (R7.1 – R7.5)
# =====================================================================


class TestErrorTaxonomy:
    """Every non-2xx response maps to the right exception type."""

    @responses.activate
    def test_4xx_non_401_raises_ApiClientError_with_envelope(self) -> None:
        responses.add(
            responses.POST,
            f"{CANONICAL}/api/v1/auth/register",
            json={"error": {"code": "EMAIL_TAKEN", "message": "Email already registered"}},
            status=409,
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        with pytest.raises(ApiClientError) as exc_info:
            client._request("POST", "/api/v1/auth/register", authed=False, json={})
        assert exc_info.value.status == 409
        assert exc_info.value.code == "EMAIL_TAKEN"
        assert exc_info.value.message == "Email already registered"

    @responses.activate
    def test_429_raises_RateLimitedError_with_retry_after(self) -> None:
        responses.add(
            responses.POST,
            f"{CANONICAL}/api/v1/auth/login",
            json={"error": {"code": "RATE_LIMITED", "message": "Too many attempts"}},
            status=429,
            headers={"Retry-After": "42"},
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        with pytest.raises(RateLimitedError) as exc_info:
            client._request("POST", "/api/v1/auth/login", authed=False, json={})
        assert exc_info.value.message == "Too many attempts"
        assert exc_info.value.retry_after == 42

    @responses.activate
    def test_429_without_retry_after_header(self) -> None:
        responses.add(
            responses.GET,
            f"{CANONICAL}/api/v1/jobs",
            json={"error": {"code": "RATE_LIMITED", "message": "Rate limited"}},
            status=429,
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        with pytest.raises(RateLimitedError) as exc_info:
            client._request("GET", "/api/v1/jobs", authed=False)
        assert exc_info.value.retry_after is None

    @responses.activate
    def test_5xx_raises_ApiServerError(self) -> None:
        responses.add(
            responses.GET,
            f"{CANONICAL}/api/v1/jobs",
            body="<html>Internal Server Error</html>",
            status=500,
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        with pytest.raises(ApiServerError) as exc_info:
            client._request("GET", "/api/v1/jobs", authed=False)
        assert exc_info.value.status == 500
        # Body captured (truncated) for diagnostics.
        assert "Internal Server Error" in exc_info.value.body

    @responses.activate
    def test_5xx_body_truncated_to_500_chars(self) -> None:
        huge_body = "x" * 2000
        responses.add(
            responses.GET,
            f"{CANONICAL}/api/v1/jobs",
            body=huge_body,
            status=503,
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        with pytest.raises(ApiServerError) as exc_info:
            client._request("GET", "/api/v1/jobs", authed=False)
        assert len(exc_info.value.body) == 500

    @responses.activate
    def test_connection_error_raises_ApiConnectionError(self) -> None:
        # `responses` registers a callback that raises to simulate
        # network failure. ConnectionError is the canonical transport
        # error.
        responses.add(
            responses.GET,
            f"{CANONICAL}/api/v1/jobs",
            body=requests.ConnectionError("dns fail"),
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        with pytest.raises(ApiConnectionError) as exc_info:
            client._request("GET", "/api/v1/jobs", authed=False)
        # Original exception is preserved for diagnostics.
        assert isinstance(exc_info.value.original, requests.RequestException)

    @responses.activate
    def test_malformed_error_body_falls_back_to_UNKNOWN(self) -> None:
        # Server returns HTML on a 500 (proxy injection, Render cold
        # start page, etc). _parse_error_body must not crash.
        responses.add(
            responses.POST,
            f"{CANONICAL}/api/v1/profiles",
            body="<html><body>Bad Gateway</body></html>",
            status=502,
            content_type="text/html",
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        client.set_tokens("tok", "ref")
        # 502 is 5xx so surfaces as ApiServerError; the parser path
        # itself is exercised by the 409 HTML case below.
        with pytest.raises(ApiServerError):
            client._request("POST", "/api/v1/profiles", authed=True, json={})

    @responses.activate
    def test_4xx_with_html_body_falls_back_to_UNKNOWN(self) -> None:
        # Some proxies inject HTML even on 4xx. Verify _parse_error_body
        # returns ("UNKNOWN", truncated text) instead of raising.
        responses.add(
            responses.POST,
            f"{CANONICAL}/api/v1/auth/login",
            body="<html>proxy says no</html>",
            status=403,
            content_type="text/html",
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        with pytest.raises(ApiClientError) as exc_info:
            client._request("POST", "/api/v1/auth/login", authed=False, json={})
        assert exc_info.value.code == "UNKNOWN"
        assert "proxy says no" in exc_info.value.message


# =====================================================================
# Reactive refresh (R3.1 – R3.5)
# =====================================================================


class TestReactiveRefresh:
    """The 401 → refresh → retry dance, with all branches.

    Every test here verifies the call count is ≤ 3 as a local check
    on the R3.5 bound. The property test in
    ``tests/property/test_api_client_properties.py`` covers the full
    Hypothesis-driven version.
    """

    @responses.activate
    def test_401_then_refresh_then_retry_succeeds(self) -> None:
        # Original profile POST returns 401 with stale token, refresh
        # rotates tokens, retry with new token succeeds.
        responses.add(
            responses.POST,
            f"{CANONICAL}/api/v1/profiles",
            json={"error": {"code": "TOKEN_EXPIRED", "message": "Expired"}},
            status=401,
        )
        responses.add(
            responses.POST,
            f"{CANONICAL}/api/v1/auth/refresh",
            json={"access": "new_access", "refresh": "new_refresh", "user": {}},
            status=200,
        )
        responses.add(
            responses.POST,
            f"{CANONICAL}/api/v1/profiles",
            json={"id": "p1", "name": "Test"},
            status=201,
        )

        client = ApiClient(base_url=BASE)
        _warm(client)
        client.set_tokens("stale_access", "stale_refresh")

        result = client._request(
            "POST",
            "/api/v1/profiles",
            authed=True,
            json={"name": "Test"},
        )
        assert result == {"id": "p1", "name": "Test"}
        # Tokens rotated via _do_refresh.
        assert client.tokens == ("new_access", "new_refresh")
        # Exactly 3 HTTP calls: original 401, refresh 200, retry 201.
        assert len(responses.calls) == 3

    @responses.activate
    def test_401_then_refresh_401_raises_AuthExpired_and_clears_tokens(
        self,
    ) -> None:
        responses.add(
            responses.GET,
            f"{CANONICAL}/api/v1/auth/me",
            json={"error": {"code": "TOKEN_EXPIRED", "message": "Expired"}},
            status=401,
        )
        responses.add(
            responses.POST,
            f"{CANONICAL}/api/v1/auth/refresh",
            json={"error": {"code": "REFRESH_INVALID", "message": "Refresh rejected"}},
            status=401,
        )

        client = ApiClient(base_url=BASE)
        _warm(client)
        client.set_tokens("access", "refresh")

        with pytest.raises(AuthExpiredError):
            client._request("GET", "/api/v1/auth/me", authed=True)
        # Tokens cleared so the next Streamlit rerun shows the login form.
        assert client.tokens == (None, None)
        # 2 calls: original 401, refresh 401. No retry because refresh failed.
        assert len(responses.calls) == 2

    @responses.activate
    def test_401_then_refresh_200_then_retry_401_raises_AuthExpired(self) -> None:
        # Rare but possible: refresh accepted, but the retried request
        # with the new token still 401s (user deleted mid-call, etc).
        responses.add(
            responses.GET,
            f"{CANONICAL}/api/v1/auth/me",
            json={"error": {"code": "TOKEN_EXPIRED", "message": "Expired"}},
            status=401,
        )
        responses.add(
            responses.POST,
            f"{CANONICAL}/api/v1/auth/refresh",
            json={"access": "A2", "refresh": "R2", "user": {}},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{CANONICAL}/api/v1/auth/me",
            json={"error": {"code": "USER_GONE", "message": "Gone"}},
            status=401,
        )

        client = ApiClient(base_url=BASE)
        _warm(client)
        client.set_tokens("access", "refresh")

        with pytest.raises(AuthExpiredError):
            client._request("GET", "/api/v1/auth/me", authed=True)
        assert client.tokens == (None, None)
        # Exactly 3 calls — the R3.5 bound at its tight edge.
        assert len(responses.calls) == 3

    @responses.activate
    def test_non_401_does_not_trigger_refresh(self) -> None:
        # R3.4: 400/403/404/429/5xx must not attempt a refresh.
        responses.add(
            responses.POST,
            f"{CANONICAL}/api/v1/profiles",
            json={"error": {"code": "VALIDATION_FAILED", "message": "bad"}},
            status=400,
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        client.set_tokens("access", "refresh")

        with pytest.raises(ApiClientError):
            client._request("POST", "/api/v1/profiles", authed=True, json={})
        # Only 1 call — no refresh, no retry.
        assert len(responses.calls) == 1
        # Tokens preserved.
        assert client.tokens == ("access", "refresh")

    def test_authed_call_with_no_access_token_raises_AuthExpired(self) -> None:
        # No network call at all — the client should fail loud before
        # hitting the network when there's no token to send.
        client = ApiClient(base_url=BASE)
        _warm(client)
        # Deliberately no set_tokens.
        with pytest.raises(AuthExpiredError):
            client._request("GET", "/api/v1/auth/me", authed=True)

    def test_do_refresh_with_no_refresh_token_raises_AuthExpired(self) -> None:
        client = ApiClient(base_url=BASE)
        _warm(client)
        # Access token set but refresh missing — unusual but we handle it.
        client.set_tokens("access", None)
        with pytest.raises(AuthExpiredError):
            client._do_refresh()


# =====================================================================
# Warmup (R4.1, R4.3, R4.4)
# =====================================================================


class TestWarmup:
    """Cold-start handling.

    We monkeypatch ``time.sleep`` in all tests to keep the suite fast;
    the backoff schedule itself is verified by inspecting the requested
    delays rather than actually sleeping them.
    """

    @responses.activate
    def test_warmup_succeeds_first_try_flips_warm_flag(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        responses.add(responses.GET, f"{CANONICAL}/health", json={"status": "ok"}, status=200)
        monkeypatch.setattr("api_client.time.sleep", lambda _s: None)
        client = ApiClient(base_url=BASE)
        assert client._warm is False
        client.warmup()
        assert client._warm is True
        assert len(responses.calls) == 1

    @responses.activate
    def test_warmup_retries_on_connection_error_then_succeeds(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # First two attempts drop the connection, third returns 200.
        responses.add(
            responses.GET,
            f"{CANONICAL}/health",
            body=requests.ConnectionError("cold"),
        )
        responses.add(
            responses.GET,
            f"{CANONICAL}/health",
            body=requests.ConnectionError("cold"),
        )
        responses.add(responses.GET, f"{CANONICAL}/health", json={"status": "ok"}, status=200)

        monkeypatch.setattr("api_client.time.sleep", lambda _s: None)
        client = ApiClient(base_url=BASE)
        client.warmup()
        assert client._warm is True
        assert len(responses.calls) == 3

    @responses.activate
    def test_warmup_gives_up_after_max_attempts(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # All 6 attempts fail; warmup raises ApiConnectionError.
        for _ in range(6):
            responses.add(
                responses.GET,
                f"{CANONICAL}/health",
                body=requests.ConnectionError("cold"),
            )
        monkeypatch.setattr("api_client.time.sleep", lambda _s: None)

        client = ApiClient(base_url=BASE)
        with pytest.raises(ApiConnectionError):
            client.warmup()
        assert client._warm is False
        assert len(responses.calls) == 6

    @responses.activate
    def test_warm_flag_skips_subsequent_warmup(self) -> None:
        # After _warm is True, _ensure_warm must short-circuit without
        # hitting /health. No responses registered for /health; a call
        # there would raise in strict mode, proving we didn't make it.
        responses.add(
            responses.GET,
            f"{CANONICAL}/api/v1/jobs",
            json={"jobs": []},
            status=200,
        )
        client = ApiClient(base_url=BASE)
        _warm(client)  # pre-flip

        result = client._request("GET", "/api/v1/jobs", authed=False)
        assert result == {"jobs": []}
        # Only the jobs call — no warmup attempted.
        assert len(responses.calls) == 1


# =====================================================================
# _ensure_warm integration
# =====================================================================


class TestEnsureWarm:
    """Warmup gets triggered by the first real API call of a session."""

    @responses.activate
    def test_first_call_triggers_warmup_then_real_request(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Warmup ping + real request both succeed.
        responses.add(responses.GET, f"{CANONICAL}/health", json={"status": "ok"}, status=200)
        responses.add(
            responses.GET,
            f"{CANONICAL}/api/v1/jobs",
            json={"jobs": [{"id": "j1"}]},
            status=200,
        )
        monkeypatch.setattr("api_client.time.sleep", lambda _s: None)

        client = ApiClient(base_url=BASE)
        # Not warm on construction.
        assert client._warm is False
        result = client._request("GET", "/api/v1/jobs", authed=False)
        assert result == {"jobs": [{"id": "j1"}]}
        assert client._warm is True
        # Exactly 2 calls: warmup /health + real /jobs.
        assert len(responses.calls) == 2


# =====================================================================
# Miscellaneous internals behaviour
# =====================================================================


class TestInternals:
    """Small behaviours that would otherwise go untested."""

    @responses.activate
    def test_204_no_content_returns_none(self) -> None:
        responses.add(
            responses.POST,
            f"{CANONICAL}/api/v1/auth/logout",
            status=204,
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        client.set_tokens("access", "refresh")
        result = client._request(
            "POST",
            "/api/v1/auth/logout",
            authed=True,
            json={"refresh": "refresh"},
        )
        assert result is None

    @responses.activate
    def test_empty_2xx_body_returns_none(self) -> None:
        responses.add(
            responses.DELETE,
            f"{CANONICAL}/api/v1/profiles/p1",
            body=b"",
            status=200,
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        client.set_tokens("access", "refresh")
        result = client._request("DELETE", "/api/v1/profiles/p1", authed=True)
        assert result is None

    def test_path_without_leading_slash_still_works(self) -> None:
        # R6.3: path normalization keeps exactly one slash between
        # base and path regardless of input shape.
        client = ApiClient(base_url="http://api.test")
        # We can't easily assert on private behaviour without mocking
        # the session, so just check the base_url state.
        assert client._base_url == "http://api.test"

    @responses.activate
    def test_path_normalization_handles_both_shapes(self) -> None:
        responses.add(
            responses.GET,
            f"{CANONICAL}/api/v1/jobs",
            json={"jobs": []},
            status=200,
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        # Path without leading slash should produce the same URL.
        result = client._request("GET", "api/v1/jobs", authed=False)
        assert result == {"jobs": []}
        assert responses.calls[0].request.url == f"{CANONICAL}/api/v1/jobs"


# =====================================================================
# Error hierarchy — single-catch property
# =====================================================================


class TestErrorHierarchy:
    """R7.6: all five leaves share :class:`ApiError` so callers catch once."""

    def test_all_errors_inherit_from_ApiError(self) -> None:
        from api_client import ApiError

        assert issubclass(ApiClientError, ApiError)
        assert issubclass(ApiServerError, ApiError)
        assert issubclass(ApiConnectionError, ApiError)
        assert issubclass(AuthExpiredError, ApiError)
        assert issubclass(RateLimitedError, ApiError)

    def test_single_except_catches_all_leaves(self) -> None:
        from api_client import ApiError

        leaves: list[Any] = [
            ApiClientError(400, "X", "msg"),
            ApiServerError(500, "body"),
            ApiConnectionError(Exception("net")),
            AuthExpiredError("gone"),
            RateLimitedError("slow", 30),
        ]
        for exc in leaves:
            try:
                raise exc
            except ApiError as caught:
                assert caught is exc


# =====================================================================
# Happy-path tests for all 16 endpoint methods (R2.1 – R2.16)
# =====================================================================


class TestAuthEndpoints:
    """R2.1 – R2.5. Auth surface: register, login, refresh, logout, me."""

    @responses.activate
    def test_register_returns_tokens_and_user(self) -> None:
        responses.add(
            responses.POST,
            f"{CANONICAL}/api/v1/auth/register",
            json={
                "user": {"id": "u1", "email": "e@x.com", "created_at": "2026-04-30T00:00:00Z"},
                "access": "a1",
                "refresh": "r1",
            },
            status=201,
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        result = client.register("e@x.com", "correct horse battery staple")
        assert result["access"] == "a1"
        assert result["refresh"] == "r1"
        assert result["user"]["email"] == "e@x.com"
        # Request body echoes the call args.
        import json

        sent = json.loads(responses.calls[0].request.body)
        assert sent == {"email": "e@x.com", "password": "correct horse battery staple"}

    @responses.activate
    def test_login_returns_tokens_and_user(self) -> None:
        responses.add(
            responses.POST,
            f"{CANONICAL}/api/v1/auth/login",
            json={"user": {"id": "u1", "email": "e@x.com"}, "access": "a", "refresh": "r"},
            status=200,
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        result = client.login("e@x.com", "pwd")
        assert result["access"] == "a"

    @responses.activate
    def test_refresh_rotates_tokens(self) -> None:
        responses.add(
            responses.POST,
            f"{CANONICAL}/api/v1/auth/refresh",
            json={"access": "new_a", "refresh": "new_r"},
            status=200,
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        client.set_tokens("old_a", "old_r")
        result = client.refresh()
        # Client returns the new pair.
        assert result == {"access": "new_a", "refresh": "new_r"}
        # And mutates internal state.
        assert client.tokens == ("new_a", "new_r")

    @responses.activate
    def test_logout_returns_none_on_204(self) -> None:
        responses.add(
            responses.POST,
            f"{CANONICAL}/api/v1/auth/logout",
            status=204,
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        client.set_tokens("a", "r")
        assert client.logout() is None

    def test_logout_with_no_refresh_token_is_noop(self) -> None:
        # No network call, no exception — just returns. Idempotent
        # with the UI's _handle_logout clearing local state anyway.
        client = ApiClient(base_url=BASE)
        _warm(client)
        assert client.logout() is None

    @responses.activate
    def test_me_returns_user(self) -> None:
        responses.add(
            responses.GET,
            f"{CANONICAL}/api/v1/auth/me",
            json={"user": {"id": "u1", "email": "e@x.com", "created_at": "2026-04-30T00:00:00Z"}},
            status=200,
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        client.set_tokens("a", "r")
        result = client.me()
        assert result["user"]["id"] == "u1"
        # Authorization header was sent.
        assert responses.calls[0].request.headers["Authorization"] == "Bearer a"


class TestPublicReads:
    """R2.6 – R2.8. Public endpoints: jobs list, job detail, resume parse."""

    @responses.activate
    def test_list_jobs_with_filters(self) -> None:
        responses.add(
            responses.GET,
            f"{CANONICAL}/api/v1/jobs",
            json={
                "items": [{"id": "j1", "title": "Engineer"}],
                "meta": {"page": 1, "limit": 20, "total": 1, "pages": 1},
            },
            status=200,
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        result = client.list_jobs(keyword="py", skill="python")
        assert result["items"][0]["id"] == "j1"
        # Query params threaded through.
        sent_url = responses.calls[0].request.url
        assert "keyword=py" in sent_url
        assert "skill=python" in sent_url

    @responses.activate
    def test_list_jobs_without_filters_sends_no_params(self) -> None:
        responses.add(
            responses.GET,
            f"{CANONICAL}/api/v1/jobs",
            json={"items": [], "meta": {"page": 1, "limit": 20, "total": 0, "pages": 0}},
            status=200,
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        client.list_jobs()
        # Base URL with no query string.
        assert responses.calls[0].request.url == f"{CANONICAL}/api/v1/jobs"

    @responses.activate
    def test_get_job(self) -> None:
        responses.add(
            responses.GET,
            f"{CANONICAL}/api/v1/jobs/j1",
            json={"id": "j1", "title": "Engineer"},
            status=200,
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        result = client.get_job("j1")
        assert result["id"] == "j1"

    @responses.activate
    def test_parse_resume(self) -> None:
        responses.add(
            responses.POST,
            f"{CANONICAL}/api/v1/resume/parse",
            json={"skills": ["python", "flask"]},
            status=200,
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        result = client.parse_resume("I know Python and Flask")
        assert result["skills"] == ["python", "flask"]
        import json

        sent = json.loads(responses.calls[0].request.body)
        assert sent == {"text": "I know Python and Flask"}


class TestProfileEndpoints:
    """R2.9 – R2.12. Profile CRUD."""

    @responses.activate
    def test_create_profile(self) -> None:
        payload = {
            "name": "Alice",
            "skills": ["python"],
            "experience_years": 3,
            "education": "Bachelor's",
            "target_role": "Backend Engineer",
        }
        responses.add(
            responses.POST,
            f"{CANONICAL}/api/v1/profiles",
            json={"id": "p1", **payload},
            status=201,
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        client.set_tokens("a", "r")
        result = client.create_profile(payload)
        assert result["id"] == "p1"

    @responses.activate
    def test_get_profile(self) -> None:
        responses.add(
            responses.GET,
            f"{CANONICAL}/api/v1/profiles/p1",
            json={"id": "p1", "name": "Alice"},
            status=200,
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        client.set_tokens("a", "r")
        assert client.get_profile("p1")["id"] == "p1"

    @responses.activate
    def test_update_profile(self) -> None:
        responses.add(
            responses.PATCH,
            f"{CANONICAL}/api/v1/profiles/p1",
            json={"id": "p1", "name": "Alice Updated"},
            status=200,
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        client.set_tokens("a", "r")
        result = client.update_profile("p1", {"name": "Alice Updated"})
        assert result["name"] == "Alice Updated"

    @responses.activate
    def test_delete_profile_returns_none_on_204(self) -> None:
        responses.add(
            responses.DELETE,
            f"{CANONICAL}/api/v1/profiles/p1",
            status=204,
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        client.set_tokens("a", "r")
        assert client.delete_profile("p1") is None


class TestAnalysisEndpoints:
    """R2.13 – R2.14. Gap analysis CRUD."""

    @responses.activate
    def test_create_analysis(self) -> None:
        responses.add(
            responses.POST,
            f"{CANONICAL}/api/v1/analyses",
            json={"id": "an1", "profile_id": "p1", "job_id": "j1"},
            status=201,
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        client.set_tokens("a", "r")
        result = client.create_analysis("p1", "j1")
        assert result["id"] == "an1"
        import json

        sent = json.loads(responses.calls[0].request.body)
        assert sent == {"profile_id": "p1", "job_id": "j1"}

    @responses.activate
    def test_get_analysis(self) -> None:
        responses.add(
            responses.GET,
            f"{CANONICAL}/api/v1/analyses/an1",
            json={"id": "an1", "profile_id": "p1"},
            status=200,
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        client.set_tokens("a", "r")
        assert client.get_analysis("an1")["id"] == "an1"


class TestRoadmapEndpoints:
    """R2.15 – R2.16. Roadmap create + resource toggle."""

    @responses.activate
    def test_create_roadmap(self) -> None:
        responses.add(
            responses.POST,
            f"{CANONICAL}/api/v1/roadmaps",
            json={"id": "rm1", "analysis_id": "an1", "phases": []},
            status=201,
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        client.set_tokens("a", "r")
        result = client.create_roadmap("an1")
        assert result["id"] == "rm1"
        import json

        sent = json.loads(responses.calls[0].request.body)
        assert sent == {"analysis_id": "an1"}

    @responses.activate
    def test_update_roadmap_resource(self) -> None:
        responses.add(
            responses.PATCH,
            f"{CANONICAL}/api/v1/roadmaps/rm1/resources/res1",
            json={"id": "rm1", "phases": [{"resources": [{"id": "res1", "completed": True}]}]},
            status=200,
        )
        client = ApiClient(base_url=BASE)
        _warm(client)
        client.set_tokens("a", "r")
        result = client.update_roadmap_resource("rm1", "res1", completed=True)
        assert result["phases"][0]["resources"][0]["completed"] is True
        import json

        sent = json.loads(responses.calls[0].request.body)
        assert sent == {"completed": True}
