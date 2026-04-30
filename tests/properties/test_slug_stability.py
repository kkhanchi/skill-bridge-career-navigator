"""Slug-stability property (R5.4).

For any permutation of ``data/jobs.json``, the slug ids produced by
``InMemoryJobRepository`` equal the slug ids in the DB after
``seed_db`` runs with that permuted file. This catches divergence
between the two code paths — the seed script reuses the in-memory
repo's slug logic, so the two should always agree.

Property 3: Slug stability across Memory → SQL transition — Validates R5.4.
"""

from __future__ import annotations

import json
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis.strategies import permutations
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.job_catalog import load_jobs
from app.db.base import Base
from app.db.models import JobORM
from app.repositories.job_repo import InMemoryJobRepository
from scripts.seed_db import seed_db


_PKG_ROOT = Path(__file__).resolve().parents[2]
_JOBS_PATH = str(_PKG_ROOT / "data" / "jobs.json")


def _load_raw_jobs() -> list[dict]:
    with open(_JOBS_PATH, encoding="utf-8") as f:
        return json.load(f)


_RAW_JOBS = _load_raw_jobs()


@settings(
    max_examples=15,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(permuted=permutations(_RAW_JOBS))
def test_seed_db_produces_same_ids_as_memory_repo(tmp_path_factory, permuted):
    # Write the permuted jobs list to a temp file (bypassing the
    # fixture system because Hypothesis + function-scoped fixtures
    # play awkwardly even with the health check suppressed).
    tmp_dir = tmp_path_factory.mktemp("perm_")
    jobs_file = tmp_dir / "jobs.json"
    jobs_file.write_text(json.dumps(permuted), encoding="utf-8")

    # Memory repo: build from the same file, extract ids.
    memory_ids = {
        rec.id for rec in InMemoryJobRepository(load_jobs(str(jobs_file)))._records
    }

    # SQL: seed into an in-memory engine, extract ids.
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        seed_db(engine=engine, jobs_path=str(jobs_file))
        with Session(engine) as session:
            sql_ids = set(session.scalars(select(JobORM.id)).all())
    finally:
        engine.dispose()

    assert sql_ids == memory_ids, (
        f"slug id sets diverged:\n"
        f"  memory: {sorted(memory_ids)}\n"
        f"  sql:    {sorted(sql_ids)}"
    )
