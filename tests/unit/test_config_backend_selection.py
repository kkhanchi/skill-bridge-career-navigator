"""Unit tests for Phase 2 config extensions.

Verifies the backend-selection-relevant config fields line up with
Phase 2 requirement R3.5, R3.6, R3.7:

- TestConfig forces memory (REPO_BACKEND="memory") so Phase 1's 89
  tests stay on the in-memory backend regardless of env.
- TestSqlConfig binds sqlite:///:memory: and does NOT override
  REPO_BACKEND, so it falls through to SQL backend selection.
- DevConfig has a SQLite file default for zero-setup `python run.py`.
- ProdConfig has no DATABASE_URL default — env required.
- CONFIG_MAP includes the new "test_sql" entry.

Requirement reference: R3.5, R3.6, R3.7.
"""

from __future__ import annotations

import pytest

from app.config import (
    CONFIG_MAP,
    BaseConfig,
    DevConfig,
    ProdConfig,
    TestConfig,
    TestSqlConfig,
)


def test_test_config_forces_memory_backend():
    # R3.5: TestConfig explicitly sets REPO_BACKEND="memory" so that
    # Phase 1's 89 tests keep running against the in-memory repos even
    # if the developer has DATABASE_URL set in their shell.
    assert TestConfig.REPO_BACKEND == "memory"


def test_test_config_has_no_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    # Re-import the class's class-level attribute — it was bound at
    # import time. Since TestConfig doesn't override DATABASE_URL,
    # it inherits BaseConfig's read which evaluated at module load.
    # We assert the behavioral contract: no environment-independent
    # fallback is set on TestConfig.
    assert "DATABASE_URL" not in vars(TestConfig)


def test_test_sql_config_uses_sqlite_in_memory():
    # R3.6: TestSqlConfig binds sqlite:///:memory: and does NOT set
    # REPO_BACKEND, so backend selection falls through to SQL.
    assert TestSqlConfig.DATABASE_URL == "sqlite:///:memory:"
    assert "REPO_BACKEND" not in vars(TestSqlConfig)


def test_test_sql_config_forces_fallback_categorizer():
    # Carries over the Phase 1 pattern — no real Groq calls from tests.
    assert TestSqlConfig.GROQ_API_KEY == ""
    assert TestSqlConfig.JSON_LOGS is False


def test_dev_config_defaults_to_sqlite_file(monkeypatch):
    # R3.7 (dev half): DevConfig.DATABASE_URL is a sqlite file URL by
    # default when the env var is absent. The class-level attribute
    # was bound at import time; assert its shape rather than trying
    # to re-evaluate under a mocked environment.
    assert DevConfig.DATABASE_URL.startswith("sqlite:///")
    assert DevConfig.DATABASE_URL.endswith("skill-bridge-dev.db")


def test_prod_config_has_no_database_url_default(monkeypatch):
    # R3.7 (prod half): ProdConfig MUST NOT provide a DATABASE_URL
    # fallback. It inherits BaseConfig's read from os.environ, which
    # returns "" when unset. If the env had a value at import time
    # we can't retroactively remove it from the class attribute, but
    # we can assert ProdConfig doesn't set its own default.
    assert "DATABASE_URL" not in vars(ProdConfig)


def test_base_config_has_phase_2_fields():
    # Structural check: the new Phase 2 keys exist on BaseConfig.
    assert hasattr(BaseConfig, "DATABASE_URL")
    assert hasattr(BaseConfig, "REPO_BACKEND")
    assert hasattr(BaseConfig, "SQLALCHEMY_ECHO")
    assert BaseConfig.SQLALCHEMY_ECHO is False


def test_config_map_includes_test_sql():
    assert "test_sql" in CONFIG_MAP
    assert CONFIG_MAP["test_sql"] is TestSqlConfig
    # Phase 1 entries preserved.
    assert CONFIG_MAP["dev"] is DevConfig
    assert CONFIG_MAP["test"] is TestConfig
    assert CONFIG_MAP["prod"] is ProdConfig
