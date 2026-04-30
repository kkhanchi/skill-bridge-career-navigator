"""Property: every ≥400 response from /auth/* matches the envelope contract (R14.6).

Sweeps the auth endpoints with random malformed bodies AND random
invalid Authorization headers. For every response with
``status_code >= 400``:

  - body is a dict with exactly one key: ``"error"``.
  - ``body["error"]["code"]`` is in the closed Phase 3 error code set.
  - ``body["error"]["message"]`` is a non-empty string.
  - response carries ``X-Correlation-ID``.

Uses ``max_examples=30`` and ``suppress_health_check`` so Hypothesis
can explore a useful range without tripping on the shared function-
scoped client.

Requirement reference: R14.6.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis.strategies import (
    dictionaries,
    just,
    one_of,
    recursive,
    sampled_from,
    text,
)

from app import create_app


# Closed set (must match app/utils/errors.py).
_VALID_CODES = {
    "VALIDATION_FAILED",
    "PROFILE_INVALID",
    "NOT_FOUND",
    "PROFILE_NOT_FOUND",
    "JOB_NOT_FOUND",
    "ANALYSIS_NOT_FOUND",
    "ROADMAP_NOT_FOUND",
    "RESOURCE_NOT_FOUND",
    "INTERNAL_ERROR",
    "METHOD_NOT_ALLOWED",
    "UNSUPPORTED_MEDIA_TYPE",
    # Phase 3
    "AUTH_REQUIRED",
    "INVALID_CREDENTIALS",
    "TOKEN_EXPIRED",
    "TOKEN_INVALID",
    "EMAIL_TAKEN",
    "RATE_LIMITED",
}


_PROPERTY_SETTINGS = settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)


_arbitrary_json_value = recursive(
    one_of(
        just(None),
        text(max_size=20),
    ),
    lambda children: dictionaries(text(min_size=1, max_size=10), children, max_size=3),
    max_leaves=5,
)

_payload_strategy = dictionaries(
    text(min_size=1, max_size=10),
    _arbitrary_json_value,
    max_size=5,
)

_endpoint_strategy = sampled_from([
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/logout"),
    ("GET", "/api/v1/auth/me"),
])

_header_strategy = one_of(
    just(None),  # no header — exercises AUTH_REQUIRED
    just({"Authorization": "Bearer not.a.jwt"}),  # TOKEN_INVALID
    just({"Authorization": "Basic not-a-bearer"}),  # AUTH_REQUIRED
)


def _fresh_client():
    return create_app("test").test_client()


@_PROPERTY_SETTINGS
@given(
    endpoint=_endpoint_strategy,
    payload=_payload_strategy,
    headers=_header_strategy,
)
def test_every_error_response_matches_envelope_closure(endpoint, payload, headers):
    """FOR ALL random (endpoint, payload, header): response ≥ 400 satisfies the envelope contract."""
    client = _fresh_client()
    method, path = endpoint

    kwargs: dict = {"method": method, "path": path}
    if method != "GET":
        kwargs["json"] = payload
    if headers is not None:
        kwargs["headers"] = headers

    response = client.open(**kwargs)

    # Only assert on >=400. 2xx / 204 are legitimate outcomes for e.g.
    # /logout with a well-formed (if meaningless) body.
    if response.status_code < 400:
        return

    body = response.get_json()
    assert isinstance(body, dict), f"body is not a dict: {body!r}"
    assert set(body.keys()) == {"error"}, f"top-level keys: {body.keys()}"
    error = body["error"]
    assert isinstance(error, dict)
    assert isinstance(error.get("code"), str) and error["code"]
    assert isinstance(error.get("message"), str) and error["message"]
    assert error["code"] in _VALID_CODES, (
        f"{method} {path} returned unknown code {error['code']!r}"
    )
    assert response.headers["X-Correlation-ID"]
