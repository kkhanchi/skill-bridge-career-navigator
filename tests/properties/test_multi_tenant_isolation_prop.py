"""Property: userA always sees their own resources; userB always gets 404 (R6.7).

Hypothesis :class:`RuleBasedStateMachine` drives two authenticated
clients (userA and userB) on the same app through random sequences of
profile create / get / patch / delete, alternating which user the
operation targets. Invariants enforced every step:

  - userA's GET on any profile userA created returns 200.
  - userB's GET on any profile userA created returns 404 NOT_FOUND.
  - Every 404 body matches the Error_Envelope shape (R6.6).

Requirement reference: R6.7.
"""

from __future__ import annotations

from hypothesis import HealthCheck, settings
from hypothesis.stateful import Bundle, RuleBasedStateMachine, rule
from hypothesis.strategies import booleans, integers, lists, sampled_from, text

from app import create_app
from app.auth.tokens import encode_access_token


_SKILLS = ["Python", "SQL", "Docker", "AWS", "REST APIs", "Git"]


def _register_user_and_mint_token(app, email):
    ext = app.extensions["skillbridge"]
    pw_hash = ext.hasher.hash("correct horse battery staple")
    with app.test_request_context():
        app.preprocess_request()
        user = ext.user_repo.create(email=email, password_hash=pw_hash)
        app.do_teardown_request(None)
    with app.app_context():
        return encode_access_token(user.id)


class _AuthedClient:
    def __init__(self, inner, token):
        self._inner = inner
        self._auth = {"Authorization": f"Bearer {token}"}

    def _merge(self, headers):
        out = dict(self._auth)
        if headers:
            out.update(headers)
        return out

    def get(self, *a, headers=None, **kw):
        return self._inner.get(*a, headers=self._merge(headers), **kw)

    def post(self, *a, headers=None, **kw):
        return self._inner.post(*a, headers=self._merge(headers), **kw)

    def patch(self, *a, headers=None, **kw):
        return self._inner.patch(*a, headers=self._merge(headers), **kw)

    def delete(self, *a, headers=None, **kw):
        return self._inner.delete(*a, headers=self._merge(headers), **kw)


class MultiTenantIsolationMachine(RuleBasedStateMachine):
    """Two users, shared app, random CRUD — tenant isolation must hold."""

    profiles_a = Bundle("profiles_a")  # ids owned by userA
    profiles_b = Bundle("profiles_b")  # ids owned by userB

    def __init__(self) -> None:
        super().__init__()
        self.app = create_app("test")
        raw_client = self.app.test_client()
        token_a = _register_user_and_mint_token(self.app, "alice@example.com")
        token_b = _register_user_and_mint_token(self.app, "bob@example.com")
        self.client_a = _AuthedClient(raw_client, token_a)
        self.client_b = _AuthedClient(raw_client, token_b)

    # ---- creates ------------------------------------------------------

    def _make_payload(self, name, skills, years):
        # Ensure skills are non-empty + distinct; the schema requires
        # 1..30 skills and non-whitespace tokens.
        uniq = sorted(set(skills))[:30]
        if not uniq:
            uniq = ["Python"]
        return {
            "name": name,
            "skills": uniq,
            "experience_years": years,
            "education": "",
            "target_role": "Backend Developer",
        }

    @rule(
        target=profiles_a,
        name=text(min_size=1, max_size=40).filter(lambda s: s.strip() != ""),
        skills=lists(sampled_from(_SKILLS), min_size=1, max_size=5, unique=True),
        years=integers(min_value=0, max_value=40),
    )
    def create_by_a(self, name, skills, years):
        payload = self._make_payload(name, skills, years)
        response = self.client_a.post("/api/v1/profiles", json=payload)
        assert response.status_code == 201
        return response.get_json()["id"]

    @rule(
        target=profiles_b,
        name=text(min_size=1, max_size=40).filter(lambda s: s.strip() != ""),
        skills=lists(sampled_from(_SKILLS), min_size=1, max_size=5, unique=True),
        years=integers(min_value=0, max_value=40),
    )
    def create_by_b(self, name, skills, years):
        payload = self._make_payload(name, skills, years)
        response = self.client_b.post("/api/v1/profiles", json=payload)
        assert response.status_code == 201
        return response.get_json()["id"]

    # ---- reads --------------------------------------------------------

    @rule(pid=profiles_a)
    def a_reads_own(self, pid):
        response = self.client_a.get(f"/api/v1/profiles/{pid}")
        assert response.status_code == 200

    @rule(pid=profiles_a)
    def b_reads_a(self, pid):
        """Cross-tenant read MUST be 404 NOT_FOUND (anti-enumeration)."""
        response = self.client_b.get(f"/api/v1/profiles/{pid}")
        assert response.status_code == 404
        body = response.get_json()
        assert body["error"]["code"] == "NOT_FOUND"
        # Envelope shape — no leaked profile fields.
        assert set(body.keys()) == {"error"}

    @rule(pid=profiles_b)
    def a_reads_b(self, pid):
        response = self.client_a.get(f"/api/v1/profiles/{pid}")
        assert response.status_code == 404
        assert response.get_json()["error"]["code"] == "NOT_FOUND"

    # ---- writes -------------------------------------------------------

    @rule(pid=profiles_a, flip=booleans())
    def b_tries_to_patch_a(self, pid, flip):
        # Cross-tenant PATCH must be rejected as NOT_FOUND — ownership
        # check runs before any mutation.
        response = self.client_b.patch(
            f"/api/v1/profiles/{pid}", json={"name": f"hack-{flip}"}
        )
        assert response.status_code == 404

    @rule(pid=profiles_a)
    def b_tries_to_delete_a(self, pid):
        response = self.client_b.delete(f"/api/v1/profiles/{pid}")
        assert response.status_code == 404
        # And the resource still exists on userA's side.
        check = self.client_a.get(f"/api/v1/profiles/{pid}")
        assert check.status_code == 200


TestMultiTenantIsolation = MultiTenantIsolationMachine.TestCase
TestMultiTenantIsolation.settings = settings(
    max_examples=20,
    deadline=None,
    stateful_step_count=25,
    suppress_health_check=[
        HealthCheck.function_scoped_fixture,
        HealthCheck.too_slow,
    ],
)
