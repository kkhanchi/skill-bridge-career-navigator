"""Unit tests for the Phase 2 engine factory.

Requirement reference: R3.4, R10.5.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine

from app.db.engine import build_engine


def test_build_engine_rejects_empty_url():
    with pytest.raises(ValueError, match="non-empty DATABASE_URL"):
        build_engine("")


def test_build_engine_rejects_unsupported_scheme():
    with pytest.raises(ValueError, match="Unsupported DATABASE_URL scheme"):
        build_engine("mysql://user:pw@host/db")


def test_build_engine_sqlite_returns_engine_without_connecting():
    # No connection is opened until first use — we can safely build
    # an engine pointing at a path that doesn't exist.
    engine = build_engine("sqlite:///:memory:")

    assert isinstance(engine, Engine)
    assert engine.url.drivername == "sqlite"


def test_build_engine_honors_echo_flag():
    engine = build_engine("sqlite:///:memory:", echo=True)
    assert engine.echo is True


def test_build_engine_defaults_echo_to_false():
    # R10.4: parameterized SQL must not leak into the log stream by
    # default. The engine factory honours that.
    engine = build_engine("sqlite:///:memory:")
    assert engine.echo is False


def test_build_engine_rewrites_bare_postgres_url_to_psycopg_driver():
    # We bundle psycopg3, not psycopg2. A bare postgresql:// URL must
    # be rewritten so SQLAlchemy picks our driver instead of failing
    # with ImportError on psycopg2.
    engine = build_engine("postgresql://user:pw@localhost/skillbridge")

    assert isinstance(engine, Engine)
    # Rewritten drivername is 'postgresql+psycopg'.
    assert engine.url.drivername == "postgresql+psycopg"


def test_build_engine_accepts_postgres_with_driver_suffix():
    # URLs like `postgresql+psycopg://...` pick a specific driver;
    # the factory should accept the `postgresql+...` family without
    # rewriting.
    engine = build_engine("postgresql+psycopg://user:pw@localhost/skillbridge")
    assert engine.url.drivername == "postgresql+psycopg"
