"""Property-based tests for :mod:`api_client`.

Four properties, each tied to a specific requirement from Phase 6's
spec. Hypothesis generates a wide distribution of inputs per
property; ``responses`` stubs the HTTP adapter so nothing touches
the network.

- **P1** — Reactive_Refresh is bounded (R3.5)
- **P3** — URL resolution ladder determinism (R1.4, R6.3)
- **P4** — Profile endpoint round-trip (R2.9, R2.10)

P2 (logout handler idempotency) lives with its handler in
``tests/unit/test_api_client.py`` because the handler is a private
helper in ``app.py``, not an ``ApiClient`` method.
"""

from __future__ import annotations

import os
from typing import Any

import responses
from hypothesis import given, settings
from hypothesis import strategies as st

from api_client import (
    ApiClient,
    ApiError,
)

BASE = "http://api.test"


def _warm(client: ApiClient) -> None:
    """Flip the client to warm so property runs don't hit warmup."""
    client._warm = True


# =====================================================================
# Feature: phase-6-streamlit-integration, Property 1: Reactive_Refresh
# bounded — R3.5
# =====================================================================


# Hypothesis strategy: generate a sequence of status codes the mocked
# server will return for successive requests. 401 + 200 + 500 + 429
# are the statuses that affect the reactive-refresh state machine;
# 204 is a successful-but-empty response common for logout.
_STATUS_CODES = st.sampled_from([200, 201, 204, 400, 401, 429, 500])


class _BoundedClient(ApiClient):
    """ApiClient subclass that counts calls to _do_request.

    Counts live on the instance so Hypothesis's many draws don't
    leak state between examples.
    """

    def __init__(self, base_url: str | None = None) -> None:
        super().__init__(base_url=base_url)
        self._call_count = 0

    def _do_request(  # type: ignore[override]
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        json: Any,
        params: dict[str, Any] | None,
        timeout: float,
    ):
        self._call_count += 1
        return super()._do_request(
            method,
            path,
            headers=headers,
            json=json,
            params=params,
            timeout=timeout,
        )


# Authed methods to probe. We invoke them via a shared helper that
# swallows the allowed exception types — the property only cares
# about the call count, not the return value.
_AUTHED_METHODS = [
    lambda c: c.me(),
    lambda c: c.create_profile(
        {
            "name": "n",
            "skills": [],
            "experience_years": 0,
            "education": "Bachelor's",
            "target_role": "t",
        }
    ),
    lambda c: c.get_profile("p1"),
    lambda c: c.update_profile("p1", {"name": "x"}),
    lambda c: c.delete_profile("p1"),
    lambda c: c.create_analysis("p1", "j1"),
    lambda c: c.get_analysis("an1"),
    lambda c: c.create_roadmap("an1"),
    lambda c: c.update_roadmap_resource("rm1", "res1", completed=True),
]


@given(
    sequence=st.lists(_STATUS_CODES, min_size=1, max_size=10),
    method_index=st.integers(min_value=0, max_value=len(_AUTHED_METHODS) - 1),
)
@settings(max_examples=100, deadline=None)
def test_pbt_reactive_refresh_bounded_by_3(
    sequence: list[int],
    method_index: int,
) -> None:
    """For any mocked response sequence, authed calls issue ≤ 3 requests.

    **Property 1: Reactive_Refresh is bounded**

    **Validates: Requirements R3.5**

    For any sequence of status codes drawn from {200, 201, 204, 400,
    401, 429, 500} and any authenticated ApiClient method, the client
    issues at most 3 HTTP requests before returning (a value) or
    raising. The client never recurses into refresh, never loops on
    a failed retry.
    """
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        # Register the response sequence against a wildcard URL via
        # a callback — any authed endpoint or refresh call hitting
        # the mock pops the next status code off the list.
        seq_iter = iter(sequence)
        fallback_status = sequence[-1]

        def _next_response(request):  # type: ignore[no-untyped-def]
            try:
                status = next(seq_iter)
            except StopIteration:
                status = fallback_status
            # Body shape depends on status: 2xx needs tokens for
            # refresh to parse, error statuses need the envelope.
            if 200 <= status < 300:
                if "/auth/refresh" in request.url:
                    body = {"access": "a", "refresh": "r"}
                elif status == 204:
                    return (status, {}, "")
                else:
                    body = {
                        "id": "x",
                        "access": "a",
                        "refresh": "r",
                        "user": {},
                        "phases": [],
                        "items": [],
                        "meta": {},
                    }
                import json as _j

                return (status, {}, _j.dumps(body))
            # Error body with the Phase 1 envelope shape.
            import json as _j

            envelope = {"error": {"code": "X", "message": "err"}}
            return (status, {"Retry-After": "1"}, _j.dumps(envelope))

        # Register the same callback for every HTTP method + a broad
        # URL match so whichever method Hypothesis picked will hit it.
        import re

        rsps.add_callback(
            responses.GET,
            re.compile(f"^{BASE}/.*"),
            callback=_next_response,
        )
        rsps.add_callback(
            responses.POST,
            re.compile(f"^{BASE}/.*"),
            callback=_next_response,
        )
        rsps.add_callback(
            responses.PATCH,
            re.compile(f"^{BASE}/.*"),
            callback=_next_response,
        )
        rsps.add_callback(
            responses.DELETE,
            re.compile(f"^{BASE}/.*"),
            callback=_next_response,
        )

        client = _BoundedClient(base_url=BASE)
        _warm(client)
        client.set_tokens("access", "refresh")

        method = _AUTHED_METHODS[method_index]
        try:
            method(client)
        except (ApiError, AssertionError):
            # Any ApiError subclass or an internal assertion (e.g.
            # the type-narrowing "body is not None" guard in an
            # endpoint method that got a 204 back when it expected a
            # JSON body) is acceptable — we're bounding the call
            # count, not the outcome.
            pass

        # R3.5 bound.
        assert client._call_count <= 3, (
            f"Expected <= 3 requests, got {client._call_count} "
            f"for sequence {sequence} method index {method_index}"
        )


# =====================================================================
# Feature: phase-6-streamlit-integration, Property 3: URL ladder
# deterministic — R1.4, R6.3
# =====================================================================


@given(
    explicit_present=st.booleans(),
    env_present=st.booleans(),
    trailing_slash=st.booleans(),
)
@settings(max_examples=50, suppress_health_check=[])
def test_pbt_url_ladder_deterministic(
    explicit_present: bool,
    env_present: bool,
    trailing_slash: bool,
) -> None:
    """For any source present/absent combination, the resolved URL is deterministic.

    **Property 3: URL resolution ladder determinism**

    **Validates: Requirements R1.4, R6.3**

    The ladder is: explicit argument → st.secrets["API_BASE_URL"] →
    os.environ["API_BASE_URL"] → "http://localhost:5000". First
    non-None source wins. Trailing slash (if any) is stripped.
    """
    # We deliberately don't test the st.secrets branch in this
    # property — test_url_ladder_streamlit_import_failure_falls_through
    # in the unit suite covers it. Property here focuses on the
    # explicit / env / default ladder under every present/absent
    # combination.
    explicit_url = "http://explicit.example" + ("/" if trailing_slash else "")
    env_url = "http://env.example" + ("/" if trailing_slash else "")

    # Manually manage env var state — Hypothesis's health check
    # rejects function-scoped monkeypatch fixtures because they
    # don't reset between examples.
    prior_env = os.environ.pop("API_BASE_URL", None)
    try:
        if env_present:
            os.environ["API_BASE_URL"] = env_url

        if explicit_present:
            client = ApiClient(base_url=explicit_url)
            expected = explicit_url.rstrip("/")
        elif env_present:
            client = ApiClient()
            expected = env_url.rstrip("/")
        else:
            client = ApiClient()
            expected = "http://localhost:5000"

        assert client._base_url == expected
    finally:
        os.environ.pop("API_BASE_URL", None)
        if prior_env is not None:
            os.environ["API_BASE_URL"] = prior_env


# =====================================================================
# Feature: phase-6-streamlit-integration, Property 4: Profile
# round-trip — R2.9, R2.10
# =====================================================================


# Profile payload strategy. Each field stays within Phase 1 validation
# bounds so the round-trip models a realistic POST + GET flow.
_name_strategy = st.text(
    alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip() != "")
_skill_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"),
        whitelist_characters=" +.-",
    ),
    min_size=1,
    max_size=30,
).filter(lambda s: s.strip() != "")
_education_strategy = st.sampled_from(["High School", "Associate", "Bachelor's", "Master's", "PhD"])
_profile_payload_strategy = st.fixed_dictionaries(
    {
        "name": _name_strategy,
        "skills": st.lists(_skill_strategy, min_size=0, max_size=10, unique=True),
        "experience_years": st.integers(min_value=0, max_value=50),
        "education": _education_strategy,
        "target_role": _name_strategy,
    }
)


@given(payload=_profile_payload_strategy)
@settings(max_examples=50, deadline=None)
def test_pbt_profile_roundtrip(payload: dict[str, Any]) -> None:
    """create_profile then get_profile returns equal field values.

    **Property 4: Profile endpoint round-trip**

    **Validates: Requirements R2.9, R2.10**

    For any valid profile payload the Phase 1 schema accepts, POSTing
    it then GETting the returned id yields a record whose
    ``(name, skills, experience_years, education, target_role)``
    tuple equals the input. Catches client-side JSON (de)serialisation
    drift, field-rename regressions, and type-coercion bugs.
    """
    import json

    # responses can't share state across a single call without a
    # callback, so we capture the POST body and echo it on GET.
    stored: dict[str, Any] = {}

    def _post_callback(request):  # type: ignore[no-untyped-def]
        body = json.loads(request.body)
        stored.update(body)
        stored["id"] = "p1"
        return (201, {}, json.dumps(stored))

    def _get_callback(request):  # type: ignore[no-untyped-def]
        return (200, {}, json.dumps(stored))

    with responses.RequestsMock() as rsps:
        rsps.add_callback(
            responses.POST,
            f"{BASE}/api/v1/profiles",
            callback=_post_callback,
        )
        rsps.add_callback(
            responses.GET,
            f"{BASE}/api/v1/profiles/p1",
            callback=_get_callback,
        )

        client = ApiClient(base_url=BASE)
        _warm(client)
        client.set_tokens("access", "refresh")

        created = client.create_profile(payload)
        fetched = client.get_profile(created["id"])

    # Tuple equality — client-side (de)serialisation is lossless.
    for key in ("name", "experience_years", "education", "target_role"):
        assert fetched[key] == payload[key], f"Mismatch on {key}"
    # skills is a list; set-equality is the right comparison because
    # Phase 1 dedups and orders skills deterministically.
    assert set(fetched["skills"]) == set(payload["skills"])
