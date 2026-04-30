"""Unit tests for :func:`app.extensions.pick_backend`.

Requirement reference: R3.1, R3.2, R3.3, R3.4.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.extensions import pick_backend


def _cfg(*, repo_backend: str = "", database_url: str = "") -> SimpleNamespace:
    """Build a duck-typed config for pick_backend."""
    return SimpleNamespace(REPO_BACKEND=repo_backend, DATABASE_URL=database_url)


def test_picks_memory_when_both_are_empty():
    # R3.2: empty config -> in-memory, no engine built.
    assert pick_backend(_cfg()) == "memory"


def test_explicit_repo_backend_wins_over_database_url():
    # R3.1: REPO_BACKEND="memory" overrides any DATABASE_URL so tests
    # can force the memory path regardless of the developer's shell.
    config = _cfg(repo_backend="memory", database_url="sqlite:///real.db")

    assert pick_backend(config) == "memory"


def test_sqlite_url_selects_sqlite_backend():
    # R3.3: sqlite: URL -> sqlite backend.
    assert pick_backend(_cfg(database_url="sqlite:///:memory:")) == "sqlite"
    assert pick_backend(_cfg(database_url="sqlite:///path/to.db")) == "sqlite"


def test_postgresql_url_selects_postgres_backend():
    # R3.3: postgresql: URL -> postgres backend.
    config = _cfg(database_url="postgresql://u:p@h/db")
    assert pick_backend(config) == "postgres"


def test_postgresql_url_with_driver_suffix_selects_postgres():
    # URLs like postgresql+psycopg://... still mean Postgres.
    config = _cfg(database_url="postgresql+psycopg://u:p@h/db")
    assert pick_backend(config) == "postgres"


def test_unsupported_scheme_raises():
    # R3.4: fail loudly at boot instead of mysterious runtime errors.
    with pytest.raises(RuntimeError, match="Unsupported DATABASE_URL scheme"):
        pick_backend(_cfg(database_url="mysql://u:p@h/db"))


def test_unsupported_explicit_repo_backend_raises():
    with pytest.raises(RuntimeError, match="Unsupported REPO_BACKEND"):
        pick_backend(_cfg(repo_backend="mongodb"))


def test_whitespace_is_trimmed():
    # Defensive: a stray space in an env var doesn't silently route
    # into an unexpected branch.
    config = _cfg(repo_backend="  memory  ", database_url="sqlite:///x.db")
    assert pick_backend(config) == "memory"


def test_explicit_sqlite_override_picks_sqlite_without_url():
    # Rare but valid: REPO_BACKEND="sqlite" without DATABASE_URL. The
    # selector says "sqlite"; init_extensions will fail later when
    # trying to build an engine from an empty URL — that's the
    # correct error surface, not pick_backend's problem.
    assert pick_backend(_cfg(repo_backend="sqlite")) == "sqlite"


def test_empty_whitespace_database_url_is_treated_as_unset():
    # os.environ may round-trip "  " if a user sets DATABASE_URL=" ".
    assert pick_backend(_cfg(database_url="   ")) == "memory"
