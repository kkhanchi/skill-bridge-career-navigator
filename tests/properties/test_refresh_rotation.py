"""Property: refresh-token rotation is one-shot (R3.7).

For any fresh refresh token R issued to a user, after one call to
/auth/refresh with R:

  - R itself is no longer valid — a second /refresh with R returns 401
    TOKEN_INVALID.
  - The new refresh R' minted by the rotation IS valid — /refresh with
    R' returns 200.

The property runs many login -> refresh -> (reuse-R, use-R') cycles
with randomized passwords so any stateful contamination across runs
would surface as a flipping counterexample.

Requirement reference: R3.7.
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


# Strategy: passwords that pass the 8..128 non-whitespace validator.
_password_strategy = (
    text(min_size=8, max_size=40).filter(lambda s: s.strip() != "")
)


def _fresh_client():
    app = create_app("test")
    return app.test_client()


@_PROPERTY_SETTINGS
@given(password=_password_strategy)
def test_refresh_old_token_dead_new_token_live(password):
    """FOR ALL valid passwords: after one /refresh, the old R is dead AND the new R is live."""
    client = _fresh_client()

    register = client.post(
        "/api/v1/auth/register",
        json={"email": "prop@example.com", "password": password},
    )
    assert register.status_code == 201
    original_refresh = register.get_json()["refresh"]

    # Rotate once.
    rotated = client.post(
        "/api/v1/auth/refresh", json={"refresh": original_refresh}
    )
    assert rotated.status_code == 200
    new_refresh = rotated.get_json()["refresh"]

    # Old token is now revoked — one-shot property.
    replay = client.post(
        "/api/v1/auth/refresh", json={"refresh": original_refresh}
    )
    assert replay.status_code == 401
    assert replay.get_json()["error"]["code"] == "TOKEN_INVALID"

    # New token works for one more rotation.
    next_rotation = client.post(
        "/api/v1/auth/refresh", json={"refresh": new_refresh}
    )
    assert next_rotation.status_code == 200
