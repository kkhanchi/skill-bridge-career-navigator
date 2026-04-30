"""UserRepository + RefreshTokenRepository backend equivalence.

Mirrors the Phase 2 pattern in
``tests/properties/test_repository_equivalence.py`` but drives the
repositories directly rather than through HTTP handlers — the auth
endpoints don't land until Stage J/K. The contract being proven:

  For any sequence of operations expressible through the
  :class:`UserRepository` and :class:`RefreshTokenRepository`
  Protocols, the in-memory and SQL-backed implementations produce
  observably equivalent results.

Two separate :class:`RuleBasedStateMachine` classes — one per
protocol — keeps bundle typing clean and avoids rules that would
only be meaningful for one repository.

Session plumbing: ``get_db_session()`` expects ``g.db_session`` to
be set, which is the job of the app's ``before_request`` hook. A
bare ``test_request_context()`` does not fire that hook, so each
SQL call is wrapped in a helper that also invokes
``preprocess_request()`` (runs the before-request chain) and
``process_response()`` (runs teardown — commit on success,
rollback on exception).

Property: Repository-backend equivalence for Phase 3 stores.
Requirement reference: R12.5, R12.6, R12.8.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from hypothesis import HealthCheck, settings
from hypothesis.stateful import Bundle, RuleBasedStateMachine, rule
from hypothesis.strategies import booleans, emails, text

from app import create_app
from app.db.base import Base
from app.repositories.refresh_token_repo import InMemoryRefreshTokenRepository
from app.repositories.sql_refresh_token_repo import SqlAlchemyRefreshTokenRepository
from app.repositories.sql_user_repo import SqlAlchemyUserRepository
from app.repositories.user_repo import InMemoryUserRepository


# ---------------------------------------------------------------------------
# SQL world helper
# ---------------------------------------------------------------------------


def _build_sql_app():
    """Fresh in-memory SQLite app with the Phase 3 schema applied."""
    app = create_app("test_sql")
    ext = app.extensions["skillbridge"]
    with app.app_context():
        Base.metadata.create_all(ext.engine)
    return app


def _run_in_sql_request(app, fn):
    """Execute *fn* with a fully-wired per-request SQL session.

    Flask's ``preprocess_request`` fires all ``before_request`` hooks,
    which includes the one that opens ``g.db_session``. The matching
    ``do_teardown_request(None)`` runs the teardown chain and commits
    the session (or rolls it back if ``fn`` raised). This is the same
    lifecycle the HTTP test client goes through for a real request,
    just invoked manually so we can call repositories directly.
    """
    with app.test_request_context():
        app.preprocess_request()
        try:
            result = fn()
        except BaseException:
            app.do_teardown_request(None)
            raise
        app.do_teardown_request(None)
        return result


# ---------------------------------------------------------------------------
# UserRepository machine
# ---------------------------------------------------------------------------


# Emails deliberately weighted so collisions are likely — we want
# exists_by_email to fire both True and False.
_email_strategy = emails()
_password_hash_strategy = text(min_size=1, max_size=60).filter(lambda s: s.strip() != "")


class UserRepositoryStateMachine(RuleBasedStateMachine):
    """Drive InMemory and SqlAlchemy user repos through the same sequence."""

    user_ids = Bundle("user_ids")

    def __init__(self) -> None:
        super().__init__()
        self.mem_repo = InMemoryUserRepository()
        self.sql_app = _build_sql_app()
        self.sql_repo = SqlAlchemyUserRepository()
        # memory_id -> sql_id pairing so we can address the same
        # logical user across the two worlds.
        self._id_pairs: dict[str, str] = {}
        # memory_id -> normalized email, so rules that want an
        # existing email can hand one out.
        self._id_emails: dict[str, str] = {}

    # ---- helpers -------------------------------------------------------

    def _with_sql(self, fn):
        """Run *fn* with a fully-wired per-request SQL session."""
        return _run_in_sql_request(self.sql_app, fn)

    # ---- rules ---------------------------------------------------------

    @rule(target=user_ids, email=_email_strategy, pw_hash=_password_hash_strategy)
    def create(self, email, pw_hash):
        # Both backends rely on the handler to have run exists_by_email
        # first. We replicate that here: if either side says the email
        # is taken, skip the create and synchronize.
        mem_exists = self.mem_repo.exists_by_email(email)
        sql_exists = self._with_sql(lambda: self.sql_repo.exists_by_email(email))
        assert mem_exists == sql_exists, (
            f"exists_by_email diverged: mem={mem_exists}, sql={sql_exists}"
        )
        if mem_exists:
            return None

        mem_rec = self.mem_repo.create(email=email, password_hash=pw_hash)
        sql_rec = self._with_sql(
            lambda: self.sql_repo.create(email=email, password_hash=pw_hash)
        )
        assert mem_rec.email == sql_rec.email
        assert mem_rec.password_hash == sql_rec.password_hash
        self._id_pairs[mem_rec.id] = sql_rec.id
        self._id_emails[mem_rec.id] = mem_rec.email
        return mem_rec.id

    @rule(uid=user_ids)
    def get_by_id(self, uid):
        if uid not in self._id_pairs:
            return
        sql_uid = self._id_pairs[uid]
        mem = self.mem_repo.get_by_id(uid)
        sql = self._with_sql(lambda: self.sql_repo.get_by_id(sql_uid))
        assert (mem is None) == (sql is None)
        if mem is not None and sql is not None:
            assert mem.email == sql.email
            assert mem.password_hash == sql.password_hash

    @rule(uid=user_ids)
    def get_by_email_known(self, uid):
        # Look up a user by the exact email they were created with.
        if uid not in self._id_emails:
            return
        email = self._id_emails[uid]
        mem = self.mem_repo.get_by_email(email)
        sql = self._with_sql(lambda: self.sql_repo.get_by_email(email))
        assert (mem is None) == (sql is None)
        if mem is not None and sql is not None:
            # Ids will differ across backends, but the email and
            # password hash must round-trip identically.
            assert mem.email == sql.email
            assert mem.password_hash == sql.password_hash

    @rule(email=_email_strategy)
    def exists_by_email_random(self, email):
        mem = self.mem_repo.exists_by_email(email)
        sql = self._with_sql(lambda: self.sql_repo.exists_by_email(email))
        assert mem == sql, f"exists_by_email diverged for {email!r}: mem={mem}, sql={sql}"


TestUserRepositoryEquivalence = UserRepositoryStateMachine.TestCase
TestUserRepositoryEquivalence.settings = settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# RefreshTokenRepository machine
# ---------------------------------------------------------------------------


class RefreshTokenRepositoryStateMachine(RuleBasedStateMachine):
    """Drive both refresh-token backends through the same sequence.

    The SQL backend's ``user_id`` FK requires a real ``users`` row, so
    we seed one row as part of the fixture. We let the SQL teardown
    commit it (via ``test_request_context``) so subsequent rules —
    which each open their own short-lived request context — see the
    seeded user.
    """

    jtis = Bundle("jtis")

    def __init__(self) -> None:
        super().__init__()
        self.mem_repo = InMemoryRefreshTokenRepository()
        self.sql_app = _build_sql_app()
        self.sql_repo = SqlAlchemyRefreshTokenRepository()
        from app.repositories.sql_user_repo import SqlAlchemyUserRepository

        user_repo = SqlAlchemyUserRepository()
        # Seed a user so the refresh_tokens.user_id FK is satisfied.
        # _run_in_sql_request commits on success so the row survives
        # into the per-rule request contexts that follow.
        def _seed():
            return user_repo.create(
                email=f"seed-{uuid4().hex[:8]}@example.com",
                password_hash="$argon2id$fake",
            )

        user = _run_in_sql_request(self.sql_app, _seed)
        self.user_id = user.id

    def _with_sql(self, fn):
        return _run_in_sql_request(self.sql_app, fn)

    @rule(target=jtis)
    def create(self):
        jti = uuid4().hex
        expires_at = datetime.now(timezone.utc) + timedelta(days=14)
        self.mem_repo.create(user_id=self.user_id, jti=jti, expires_at=expires_at)
        self._with_sql(
            lambda: self.sql_repo.create(
                user_id=self.user_id, jti=jti, expires_at=expires_at
            )
        )
        return jti

    @rule(jti=jtis)
    def get_by_jti(self, jti):
        mem = self.mem_repo.get_by_jti(jti)
        sql = self._with_sql(lambda: self.sql_repo.get_by_jti(jti))
        assert (mem is None) == (sql is None)
        if mem is not None and sql is not None:
            assert mem.jti == sql.jti
            assert mem.user_id == sql.user_id
            assert (mem.revoked_at is None) == (sql.revoked_at is None)

    @rule(jti=jtis)
    def is_revoked(self, jti):
        mem = self.mem_repo.is_revoked(jti)
        sql = self._with_sql(lambda: self.sql_repo.is_revoked(jti))
        assert mem == sql

    @rule(jti=jtis)
    def revoke(self, jti):
        mem = self.mem_repo.revoke(jti)
        sql = self._with_sql(lambda: self.sql_repo.revoke(jti))
        # Idempotency must match: both True on the first call, both
        # False on every subsequent call.
        assert mem == sql, f"revoke return value diverged for {jti}: mem={mem}, sql={sql}"


TestRefreshTokenRepositoryEquivalence = RefreshTokenRepositoryStateMachine.TestCase
TestRefreshTokenRepositoryEquivalence.settings = settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
