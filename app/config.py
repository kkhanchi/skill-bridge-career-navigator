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

    # --- Phase 3: authentication & authorization -------------------------
    # JWT_SECRET signs all access + refresh JWTs (HS256). Empty default on
    # BaseConfig; DevConfig overrides with a loud dev literal; TestConfig
    # overrides with a fixed test literal; ProdConfig has no default and
    # the app factory raises if the env var is unset (R9.1).
    JWT_SECRET: str = os.environ.get("JWT_SECRET", "")
    # TTLs are deliberately small vs large: access tokens are short-lived
    # and stateless; refresh tokens are 14 days and stateful (stored in
    # refresh_tokens table) so they can be revoked.
    ACCESS_TTL_SECONDS: int = 900            # 15 minutes
    REFRESH_TTL_SECONDS: int = 1_209_600     # 14 days

    # argon2id cost parameters — see OWASP guidance. DevConfig/ProdConfig
    # use these production defaults; TestConfig weakens them by two orders
    # of magnitude so the test suite doesn't block on hashing.
    ARGON2_TIME_COST: int = 2
    ARGON2_MEMORY_COST: int = 65536           # KiB (64 MiB)
    ARGON2_PARALLELISM: int = 4

    # Comma-separated origin allowlist. Empty string means "no CORS init"
    # (same-origin only). "*" means wildcard. Prod has no default and
    # requires explicit operator opt-in (R13.5).
    CORS_ORIGINS: str = os.environ.get("CORS_ORIGINS", "")


class DevConfig(BaseConfig):
    """Local development: verbose JSON logs, Groq key read from env.

    Phase 2: defaults `DATABASE_URL` to a local SQLite file so that
    `python run.py` works without any env setup. An explicit
    `DATABASE_URL` env var takes precedence.

    Phase 3: provides a dev-only default `JWT_SECRET` and a permissive
    `CORS_ORIGINS = "*"`. Both get a startup warning so developers are
    not surprised when a misconfigured prod boot deviates from dev.
    """

    LOG_LEVEL = "DEBUG"
    DATABASE_URL = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{_PKG_ROOT / 'skill-bridge-dev.db'}",
    )
    # The `_DEV_JWT_SECRET_DEFAULT_SENTINEL` string is recognized by the
    # app factory (Stage J task 57) so a startup warning fires when the
    # default is in effect. Operators who set JWT_SECRET in the env get
    # no warning.
    JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-do-not-use-in-prod")
    CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*")


class TestConfig(BaseConfig):
    """Test runs: deterministic fallback categorizer, plain-text logs.

    Tests assert on log lines and must not depend on Groq network calls.
    Phase 2: `REPO_BACKEND="memory"` is explicitly forced so that all 89
    Phase 1 tests continue to run against the in-memory repositories as
    a regression baseline — independent of whatever DATABASE_URL the
    developer has in their shell (R3.5).

    Phase 3: argon2 cost parameters are dropped two orders of magnitude
    so the ~40 auth-touching tests don't spend seconds hashing. These
    values are NEVER to be used in production — they are safe only
    because TestConfig is never the running config in a deployed
    container.
    """

    APP_ENV = "test"
    JSON_LOGS = False
    GROQ_API_KEY = ""
    REPO_BACKEND = "memory"
    # Phase 3:
    JWT_SECRET = "test-secret-literal"
    ARGON2_TIME_COST = 1
    ARGON2_MEMORY_COST = 8       # KiB — deliberately weak for test speed
    ARGON2_PARALLELISM = 1
    CORS_ORIGINS = ""


class TestSqlConfig(BaseConfig):
    """Test runs against the SQL backend (Phase 2).

    Uses an in-process SQLite database that vanishes when the test
    Python process exits. Selected via ``create_app("test_sql")``.

    Phase 3: inherits TestConfig's weakened argon2 params and the fixed
    test JWT_SECRET so SQL-backend auth tests don't spend real argon2
    cycles either.
    """

    APP_ENV = "test"
    JSON_LOGS = False
    GROQ_API_KEY = ""
    DATABASE_URL = "sqlite:///:memory:"
    # Phase 3: match TestConfig.
    JWT_SECRET = "test-secret-literal"
    ARGON2_TIME_COST = 1
    ARGON2_MEMORY_COST = 8
    ARGON2_PARALLELISM = 1
    CORS_ORIGINS = ""


class ProdConfig(BaseConfig):
    """Production defaults (gunicorn / wsgi)."""

    APP_ENV = "prod"


CONFIG_MAP: dict[str, type[BaseConfig]] = {
    "dev": DevConfig,
    "test": TestConfig,
    "test_sql": TestSqlConfig,
    "prod": ProdConfig,
}
