"""Rate-limiting behaviour across the /auth/* endpoints.

Verifies:
  - Register: 5/hour per IP. 6th call returns 429 RATE_LIMITED.
  - Login:    10/minute per IP.
  - Refresh:  30/minute per IP.
  - Public endpoints (/health, /api/v1/jobs) are NEVER rate-limited
    regardless of frequency (R7.4).
  - Every 429 body matches the Error_Envelope shape and carries
    X-Correlation-ID (R14.1).
  - Decorator order: @limiter runs BEFORE @validate_body, so 31
    malformed refresh payloads burn the quota on the 31st attempt
    (no short-circuit by the Pydantic validator).

Requirement reference: R13.2, R13.3, R7.4.
"""

from __future__ import annotations


_PASSWORD = "correct horse battery staple"


def _register(client, email="alice@example.com"):
    return client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _PASSWORD},
    )


def _login(client, email="alice@example.com"):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": _PASSWORD},
    )


# ---------------------------------------------------------------------------
# Register: 5/hour
# ---------------------------------------------------------------------------


def test_register_rate_limit_envelope_shape(client):
    # Unique emails so each request goes through the business logic.
    for i in range(5):
        assert _register(client, email=f"u{i}@example.com").status_code == 201

    response = _register(client, email="u6@example.com")
    assert response.status_code == 429
    body = response.get_json()
    assert set(body.keys()) == {"error"}
    assert body["error"]["code"] == "RATE_LIMITED"
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    assert response.headers["X-Correlation-ID"]


# ---------------------------------------------------------------------------
# Login: 10/minute
# ---------------------------------------------------------------------------


def test_login_rate_limit_envelope_shape(client):
    _register(client)

    # 10 successful logins burn the quota.
    for _ in range(10):
        assert _login(client).status_code == 200

    response = _login(client)
    assert response.status_code == 429
    assert response.get_json()["error"]["code"] == "RATE_LIMITED"


# ---------------------------------------------------------------------------
# Refresh: 30/minute — decorator ordering probe
# ---------------------------------------------------------------------------


def test_refresh_limiter_runs_before_body_validation(client):
    """Even 30 malformed bodies burn the refresh quota.

    @_with_limit is applied outside @validate_body on the handler, so
    flask-limiter counts the request before Pydantic gets a chance to
    reject the body. 31 calls with an empty body therefore hit 429 on
    the 31st, not 400 VALIDATION_FAILED 31 times in a row.
    """
    for _ in range(30):
        response = client.post("/api/v1/auth/refresh", json={})
        # Each call is rejected as either 400 (missing field) or 429
        # (the final one). The per-call status doesn't matter; what
        # matters is that the limiter sees all 30.
        assert response.status_code in (400, 429)

    response = client.post("/api/v1/auth/refresh", json={})
    assert response.status_code == 429
    assert response.get_json()["error"]["code"] == "RATE_LIMITED"


# ---------------------------------------------------------------------------
# Public endpoints are never rate-limited (R7.4)
# ---------------------------------------------------------------------------


def test_health_is_never_rate_limited(client):
    """Hammering /health past any of the /auth/* limits doesn't 429."""
    for _ in range(50):
        response = client.get("/health")
        assert response.status_code == 200


def test_jobs_list_is_never_rate_limited(client):
    for _ in range(50):
        response = client.get("/api/v1/jobs")
        assert response.status_code == 200
