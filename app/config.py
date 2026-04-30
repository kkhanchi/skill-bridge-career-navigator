"""Environment-based configuration for the SkillBridge Flask API.

Three named configurations are selected at startup via the ``config_name``
argument to :func:`app.create_app`: ``"dev"``, ``"test"``, ``"prod"``.

Design reference: `.kiro/specs/phase-1-rest-api/design.md` §Components/config.
Requirement reference: R10.1, R10.3, R10.4.
"""

from __future__ import annotations

import os
from pathlib import Path


# Paths are resolved relative to the ``skill-bridge/`` package root (two
# levels up from this file: ``skill-bridge/app/config.py``). This keeps the
# configuration stable regardless of where the Flask process is launched
# from — dev server, gunicorn, pytest all see the same data directory.
_PKG_ROOT = Path(__file__).resolve().parents[1]


class BaseConfig:
    """Defaults shared by every environment."""

    APP_ENV: str = "dev"

    # Logging
    JSON_LOGS: bool = True
    LOG_LEVEL: str = "INFO"

    # External services
    GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")

    # Data files loaded once by init_extensions()
    JOBS_PATH: str = str(_PKG_ROOT / "data" / "jobs.json")
    TAXONOMY_PATH: str = str(_PKG_ROOT / "data" / "skill_taxonomy.json")
    RESOURCES_PATH: str = str(_PKG_ROOT / "data" / "learning_resources.json")

    # Pagination
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100

    # --- Phase 2: persistence --------------------------------------------
    # Empty string means "no SQL backend — use the in-memory repositories".
    # `REPO_BACKEND` is an explicit override ("memory" | "sqlite" | "postgres")
    # that wins over DATABASE_URL when set; Extensions.pick_backend uses it
    # to force the in-memory path in tests even if a real DATABASE_URL is
    # present in the developer's shell environment.
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "")
    REPO_BACKEND: str = os.environ.get("REPO_BACKEND", "")
    SQLALCHEMY_ECHO: bool = False


class DevConfig(BaseConfig):
    """Local development: verbose JSON logs, Groq key read from env.

    Phase 2: defaults `DATABASE_URL` to a local SQLite file so that
    `python run.py` works without any env setup. An explicit
    `DATABASE_URL` env var takes precedence.
    """

    LOG_LEVEL = "DEBUG"
    DATABASE_URL = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{_PKG_ROOT / 'skill-bridge-dev.db'}",
    )


class TestConfig(BaseConfig):
    """Test runs: deterministic fallback categorizer, plain-text logs.

    Tests assert on log lines and must not depend on Groq network calls.
    Phase 2: `REPO_BACKEND="memory"` is explicitly forced so that all 89
    Phase 1 tests continue to run against the in-memory repositories as
    a regression baseline — independent of whatever DATABASE_URL the
    developer has in their shell (R3.5).
    """

    APP_ENV = "test"
    JSON_LOGS = False
    GROQ_API_KEY = ""
    REPO_BACKEND = "memory"


class TestSqlConfig(BaseConfig):
    """Test runs against the SQL backend (Phase 2).

    Uses an in-process SQLite database that vanishes when the test
    Python process exits. Selected via ``create_app("test_sql")``.
    """

    APP_ENV = "test"
    JSON_LOGS = False
    GROQ_API_KEY = ""
    DATABASE_URL = "sqlite:///:memory:"


class ProdConfig(BaseConfig):
    """Production defaults (gunicorn / wsgi)."""

    APP_ENV = "prod"


CONFIG_MAP: dict[str, type[BaseConfig]] = {
    "dev": DevConfig,
    "test": TestConfig,
    "test_sql": TestSqlConfig,
    "prod": ProdConfig,
}
