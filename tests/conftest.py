"""Shared test fixtures for Skill-Bridge Career Navigator."""

import sys
import os
import pytest

# Add parent directory to path so modules can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import UserProfile, JobPosting, LearningResource


@pytest.fixture
def sample_profile():
    return UserProfile(
        name="Jane Doe",
        skills=["Python", "SQL", "Git"],
        experience_years=2,
        education="Bachelor's",
        target_role="Backend Developer",
    )


@pytest.fixture
def sample_job():
    return JobPosting(
        title="Backend Developer",
        description="Build scalable APIs",
        required_skills=["Python", "SQL", "REST APIs", "Git"],
        preferred_skills=["Docker", "AWS", "Redis"],
        experience_level="Mid",
    )


@pytest.fixture
def sample_taxonomy():
    return [
        "Python", "Java", "JavaScript", "SQL", "REST APIs", "Git",
        "Docker", "AWS", "Redis", "React", "Machine Learning",
    ]


@pytest.fixture
def sample_resources():
    return [
        LearningResource(name="REST API Course", skill="REST APIs",
                         resource_type="course", estimated_hours=12,
                         url="https://example.com/rest"),
        LearningResource(name="Docker Essentials", skill="Docker",
                         resource_type="course", estimated_hours=12,
                         url="https://example.com/docker"),
        LearningResource(name="AWS Cloud Practitioner", skill="AWS",
                         resource_type="certification", estimated_hours=25,
                         url="https://example.com/aws"),
        LearningResource(name="Redis Caching", skill="Redis",
                         resource_type="course", estimated_hours=8,
                         url="https://example.com/redis"),
    ]

# ---------------------------------------------------------------------------
# Flask integration fixtures (added in Phase 1 / Stage B).
#
# Each integration test gets a fresh ``create_app("test")`` instance so
# in-memory repositories stay isolated across tests (R10.2).
# ---------------------------------------------------------------------------

from app import create_app


@pytest.fixture
def app():
    """Build a fresh Flask app configured for tests (TestConfig)."""
    return create_app("test")


@pytest.fixture
def client(app):
    """Flask test client bound to the per-test app instance."""
    return app.test_client()


# ---------------------------------------------------------------------------
# Phase 2 SQL fixtures.
#
# `sql_app` / `sql_client` parallel the Phase 1 `app` / `client` fixtures
# but bind the SQL backend via create_app("test_sql"). The schema is
# applied via Base.metadata.create_all for speed; Alembic migration
# correctness is tested separately in test_alembic_smoke.py. Each test
# gets a fresh in-memory SQLite DB so state is isolated per-test.
# ---------------------------------------------------------------------------

from app.db.base import Base as _Base


@pytest.fixture
def sql_app():
    """Flask app bound to sqlite:///:memory: with the Phase 2 schema applied."""
    app = create_app("test_sql")
    ext = app.extensions["skillbridge"]
    with app.app_context():
        _Base.metadata.create_all(ext.engine)
    yield app


@pytest.fixture
def sql_client(sql_app):
    """Flask test client bound to the per-test SQL app instance."""
    return sql_app.test_client()


# ---------------------------------------------------------------------------
# Phase 3 auth fixtures.
#
# ``test_user`` registers a fresh user on each test's app via the
# wired ``user_repo`` + ``hasher`` in Extensions. ``access_token``
# mints a valid JWT for that user. ``authenticated_client`` wraps
# the plain test client with a default Authorization header so
# existing Phase 1/2 integration tests can slot straight into the
# protected endpoints with a one-line fixture swap (R14.5).
#
# Memory-backed and SQL-backed variants share this path — the
# ``test_user`` fixture picks up whichever app fixture the test
# requested (``app`` vs ``sql_app``) because it depends only on
# ``user_repo.create``, which is Protocol-defined.
# ---------------------------------------------------------------------------

from app.auth.tokens import encode_access_token


_TEST_USER_PASSWORD = "correct horse battery staple"


def _register_user(app, email: str):
    """Create a user directly through the Extensions user_repo.

    For the SQL backend this runs inside the request lifecycle so
    ``before_request`` opens a session and ``teardown_request`` commits
    it. For memory, the same call path is valid — ``test_request_context``
    is harmless on an app that has no SQL hooks.
    """
    ext = app.extensions["skillbridge"]
    password_hash = ext.hasher.hash(_TEST_USER_PASSWORD)
    with app.test_request_context():
        app.preprocess_request()
        user = ext.user_repo.create(email=email, password_hash=password_hash)
        app.do_teardown_request(None)
    return user


@pytest.fixture
def test_user(app):
    """A single pre-registered user on the memory-backed app."""
    return _register_user(app, "alice@example.com")


@pytest.fixture
def second_user(app):
    """A second user for multi-tenant isolation tests."""
    return _register_user(app, "bob@example.com")


@pytest.fixture
def sql_test_user(sql_app):
    """Pre-registered user on the SQL-backed app."""
    return _register_user(sql_app, "alice@example.com")


@pytest.fixture
def sql_second_user(sql_app):
    return _register_user(sql_app, "bob@example.com")


def _mint_access(app, user) -> str:
    """Mint an access token for *user* inside *app*'s context."""
    with app.app_context():
        return encode_access_token(user.id)


@pytest.fixture
def access_token(app, test_user):
    return _mint_access(app, test_user)


@pytest.fixture
def second_access_token(app, second_user):
    return _mint_access(app, second_user)


@pytest.fixture
def sql_access_token(sql_app, sql_test_user):
    return _mint_access(sql_app, sql_test_user)


@pytest.fixture
def sql_second_access_token(sql_app, sql_second_user):
    return _mint_access(sql_app, sql_second_user)


class _AuthedClient:
    """Flask test client that injects ``Authorization: Bearer <token>``.

    Wraps ``app.test_client()`` so every verb method
    (``get``/``post``/``patch``/``delete``) folds the default header
    into whatever ``headers=`` the caller passes. Keeps Phase 1/2
    test bodies unchanged — they just switch the ``client`` fixture
    for ``authenticated_client``.
    """

    def __init__(self, client, token: str) -> None:
        self._client = client
        self._default_headers = {"Authorization": f"Bearer {token}"}

    def _merge_headers(self, headers):
        merged = dict(self._default_headers)
        if headers:
            merged.update(headers)
        return merged

    def get(self, *args, headers=None, **kwargs):
        return self._client.get(*args, headers=self._merge_headers(headers), **kwargs)

    def post(self, *args, headers=None, **kwargs):
        return self._client.post(*args, headers=self._merge_headers(headers), **kwargs)

    def patch(self, *args, headers=None, **kwargs):
        return self._client.patch(*args, headers=self._merge_headers(headers), **kwargs)

    def delete(self, *args, headers=None, **kwargs):
        return self._client.delete(
            *args, headers=self._merge_headers(headers), **kwargs
        )

    def put(self, *args, headers=None, **kwargs):
        return self._client.put(*args, headers=self._merge_headers(headers), **kwargs)

    def open(self, *args, headers=None, **kwargs):
        return self._client.open(*args, headers=self._merge_headers(headers), **kwargs)


@pytest.fixture
def authenticated_client(client, access_token):
    """Memory-backed Flask test client with a default Bearer token."""
    return _AuthedClient(client, access_token)


@pytest.fixture
def second_authenticated_client(client, second_access_token):
    """A second memory-backed client for multi-tenant isolation tests."""
    return _AuthedClient(client, second_access_token)


@pytest.fixture
def authenticated_sql_client(sql_client, sql_access_token):
    """SQL-backed Flask test client with a default Bearer token."""
    return _AuthedClient(sql_client, sql_access_token)


@pytest.fixture
def second_authenticated_sql_client(sql_client, sql_second_access_token):
    return _AuthedClient(sql_client, sql_second_access_token)
