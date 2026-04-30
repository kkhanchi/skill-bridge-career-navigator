"""Alembic upgrade/downgrade smoke test.

Builds an Alembic :class:`Config` programmatically, runs
``upgrade head`` against a temporary SQLite file, introspects the
resulting schema, and then runs ``downgrade base`` / ``upgrade head``
again — asserting the table + index set stays identical across the
round trip.

This test is the R1.6 migration round-trip property in concrete form
(single example rather than a Hypothesis search, which is appropriate
for a schema that's deterministic by construction).

Requirement reference: R1.1, R1.2, R1.6.
"""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


_PKG_ROOT = Path(__file__).resolve().parents[2]


def _build_alembic_config(db_path: Path) -> Config:
    """Build an Alembic Config pointing at *db_path*.

    Sets ``sqlalchemy.url`` on the Config directly so env.py picks it
    up via ``config.get_main_option("sqlalchemy.url")`` without
    needing to set APP_ENV.
    """
    config = Config(str(_PKG_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_PKG_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return config


def _introspect(db_url: str) -> tuple[set[str], dict[str, set[tuple[str, ...]]], dict[str, set[tuple[str, ...]]]]:
    """Return (tables, indexes, unique_constraints) for the DB.

    ``indexes`` maps table -> set of column-tuples for single/multi-column
    indexes. ``unique_constraints`` is the parallel map for UNIQUE
    constraints emitted as constraints rather than indexes (e.g. SQLite
    represents ``UNIQUE`` as a constraint, not a separate index).
    """
    engine = create_engine(db_url)
    try:
        insp = inspect(engine)
        tables = set(insp.get_table_names())
        indexes: dict[str, set[tuple[str, ...]]] = {}
        uniques: dict[str, set[tuple[str, ...]]] = {}
        for table in tables:
            indexes[table] = {
                tuple(idx["column_names"]) for idx in insp.get_indexes(table)
            }
            uniques[table] = {
                tuple(u["column_names"]) for u in insp.get_unique_constraints(table)
            }
        return tables, indexes, uniques
    finally:
        engine.dispose()


def test_upgrade_head_creates_expected_tables_and_indexes(tmp_path):
    db_file = tmp_path / "alembic_smoke.db"
    config = _build_alembic_config(db_file)

    command.upgrade(config, "head")

    tables, indexes, uniques = _introspect(f"sqlite:///{db_file}")
    # Alembic adds its own `alembic_version` bookkeeping table — we
    # assert the Phase 2 + Phase 3 set is a subset of whatever's present.
    expected = {
        "users",
        "profiles",
        "jobs",
        "analyses",
        "roadmaps",
        "refresh_tokens",
    }
    assert expected.issubset(tables)

    # R1.2: verify every expected column-level index is present.
    assert ("user_id",) in indexes["profiles"]
    assert ("title",) in indexes["jobs"]
    assert ("experience_level",) in indexes["jobs"]
    assert ("profile_id",) in indexes["analyses"]
    assert ("job_id",) in indexes["analyses"]
    assert ("analysis_id",) in indexes["roadmaps"]
    # Phase 3: refresh_tokens.user_id is explicitly indexed.
    assert ("user_id",) in indexes["refresh_tokens"]

    # UNIQUE on users.email surfaces via get_unique_constraints, not
    # get_indexes (SQLite represents UNIQUE as a constraint rather than
    # an index with unique=True).
    assert ("email",) in uniques["users"]
    # Phase 3: UNIQUE on refresh_tokens.jti likewise.
    assert ("jti",) in uniques["refresh_tokens"]

    # Phase 3 (migration 0002): profiles.user_id and analyses.user_id
    # are NOT NULL after the flip.
    from sqlalchemy import create_engine, inspect as sa_inspect

    eng = create_engine(f"sqlite:///{db_file}")
    try:
        insp = sa_inspect(eng)
        profiles_user_id = next(
            c for c in insp.get_columns("profiles") if c["name"] == "user_id"
        )
        assert profiles_user_id["nullable"] is False
        analyses_user_id = next(
            c for c in insp.get_columns("analyses") if c["name"] == "user_id"
        )
        assert analyses_user_id["nullable"] is False
    finally:
        eng.dispose()


def test_upgrade_downgrade_round_trip_is_symmetric(tmp_path):
    # R1.6: running upgrade -> downgrade -> upgrade leaves the schema
    # in the same state as a single upgrade. Catches migration drift
    # where downgrade doesn't fully reverse upgrade.
    db_file = tmp_path / "alembic_symmetry.db"
    config = _build_alembic_config(db_file)

    command.upgrade(config, "head")
    tables_first, indexes_first, uniques_first = _introspect(f"sqlite:///{db_file}")

    command.downgrade(config, "base")
    tables_empty, _, _ = _introspect(f"sqlite:///{db_file}")
    # After downgrade base, no Phase 2/3 tables remain.
    assert tables_empty.isdisjoint(
        {
            "users",
            "profiles",
            "jobs",
            "analyses",
            "roadmaps",
            "refresh_tokens",
        }
    )

    command.upgrade(config, "head")
    tables_again, indexes_again, uniques_again = _introspect(f"sqlite:///{db_file}")

    assert tables_again == tables_first
    assert indexes_again == indexes_first
    assert uniques_again == uniques_first


def test_downgrade_base_reverses_all_tables(tmp_path):
    db_file = tmp_path / "alembic_downgrade.db"
    config = _build_alembic_config(db_file)

    command.upgrade(config, "head")
    command.downgrade(config, "base")

    tables, _, _ = _introspect(f"sqlite:///{db_file}")
    for table in (
        "users",
        "profiles",
        "jobs",
        "analyses",
        "roadmaps",
        "refresh_tokens",
    ):
        assert table not in tables
