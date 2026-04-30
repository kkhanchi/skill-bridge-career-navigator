"""Property: logout revokes the presented refresh, and is idempotent (R4.4).

For any valid refresh token R:
  1. POST /logout {refresh: R} returns 204 and revokes R.
  2. A subsequent POST /refresh {refresh: R} returns 401 TOKEN_INVALID.
  3. A subsequent POST /logout {refresh: R} returns 204 again
     (idempotency — already-revoked is NOT an error).

Runs for arbitrary valid passwords so any stateful contamination
would flip the invariant on a subsequent example.

Requirement reference: R4.4.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis.strategies import text

from app import create_app


_PROPERTY_SETTINGS = settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)

_password_strategy = (
    text(min_size=8, max_size=40).filter(lambda s: s.strip() != "")
)


def _fresh_client():
    app = create_app("test")
    return app.test_client()


@_PROPERTY_SETTINGS
@given(password=_password_strategy)
def test_logout_is_one_shot_revocation_and_idempotent(password):
    client = _fresh_client()

    register = client.post(
        "/api/v1/auth/register",
        json={"email": "prop@example.com", "password": password},
    )
    assert register.status_code == 201
    refresh = register.get_json()["refresh"]

    # First logout revokes.
    first = client.post("/api/v1/auth/logout", json={"refresh": refresh})
    assert first.status_code == 204

    # Refresh with R is rejected.
    replay = client.post("/api/v1/auth/refresh", json={"refresh": refresh})
    assert replay.status_code == 401
    assert replay.get_json()["error"]["code"] == "TOKEN_INVALID"

    # Second logout is idempotent — still 204 even though R is revoked.
    second = client.post("/api/v1/auth/logout", json={"refresh": refresh})
    assert second.status_code == 204
