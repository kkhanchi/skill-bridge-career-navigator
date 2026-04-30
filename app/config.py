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


class DevConfig(BaseConfig):
    """Local development: verbose JSON logs, Groq key read from env."""

    LOG_LEVEL = "DEBUG"


class TestConfig(BaseConfig):
    """Test runs: deterministic fallback categorizer, plain-text logs.

    Tests assert on log lines and must not depend on Groq network calls.
    """

    APP_ENV = "test"
    JSON_LOGS = False
    GROQ_API_KEY = ""


class ProdConfig(BaseConfig):
    """Production defaults (gunicorn / wsgi)."""

    APP_ENV = "prod"


CONFIG_MAP: dict[str, type[BaseConfig]] = {
    "dev": DevConfig,
    "test": TestConfig,
    "prod": ProdConfig,
}
