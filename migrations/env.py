"""Alembic environment.

Pulls the SQLAlchemy URL from the active Flask config at runtime
(``CONFIG_MAP[APP_ENV].DATABASE_URL``) rather than reading it from
``alembic.ini``. This keeps one source of truth for connection strings
and avoids hardcoding credentials in a versioned file.

Target metadata is :attr:`app.db.base.Base.metadata` so
``alembic revision --autogenerate`` sees every declarative model
under :mod:`app.db.models`.

Requirement reference: R1.1, R3.7.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure the skill-bridge package root is importable so `from app.db.base`
# resolves whether Alembic is run from `skill-bridge/` or from a tool
# that spawns it from elsewhere.
_PKG_ROOT = Path(__file__).resolve().parents[1]
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from app.config import CONFIG_MAP  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.models import (  # noqa: E402, F401  -- registers mappers with Base
    AnalysisORM,
    JobORM,
    ProfileORM,
    RoadmapORM,
    UserORM,
)

# Alembic config object — provides access to values in alembic.ini.
config = context.config

# Wire logging from alembic.ini.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _resolve_database_url() -> str:
    """Pull DATABASE_URL from the active Flask config.

    Precedence:
      1. Explicit ``sqlalchemy.url`` on the Alembic Config (set by tests
         that drive Alembic programmatically).
      2. ``CONFIG_MAP[APP_ENV].DATABASE_URL`` from the app config layer.

    Raises:
        RuntimeError: When neither is set — fail loud rather than run
            migrations against an unexpected default DB.
    """
    explicit = config.get_main_option("sqlalchemy.url")
    if explicit:
        return explicit

    app_env = os.environ.get("APP_ENV", "dev").strip() or "dev"
    if app_env not in CONFIG_MAP:
        raise RuntimeError(
            f"Unknown APP_ENV {app_env!r}; expected one of {sorted(CONFIG_MAP)}"
        )
    cfg = CONFIG_MAP[app_env]
    url = str(getattr(cfg, "DATABASE_URL", "") or "").strip()
    if not url:
        raise RuntimeError(
            f"DATABASE_URL is empty on APP_ENV={app_env!r}; set it in the "
            f"environment or pass -x sqlalchemy.url=... to alembic."
        )
    return url


# Metadata Alembic autogenerate compares against the live DB schema.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL statements to stdout without connecting to a DB."""
    url = _resolve_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the DB and apply migrations."""
    # Inject the resolved URL into the Alembic section so
    # engine_from_config picks it up.
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _resolve_database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
