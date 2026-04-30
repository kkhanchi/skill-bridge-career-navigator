"""Seed-idempotency property (R5.2).

For any N >= 1, running ``seed_db`` N times against the same
``data/jobs.json`` produces the same final DB state as running it
once. We hash every row into a stable tuple and compare multisets.

Property 2: Seed idempotency — Validates R5.2.
"""

from __future__ import annotations

from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis.strategies import integers
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import JobORM
from scripts.seed_db import seed_db


_PKG_ROOT = Path(__file__).resolve().parents[2]
_JOBS_PATH = str(_PKG_ROOT / "data" / "jobs.json")


def _row_tuples(engine) -> list[tuple]:
    with Session(engine) as session:
        rows = session.scalars(select(JobORM).order_by(JobORM.id.asc())).all()
        return [
            (
                r.id,
                r.title,
                r.description,
                tuple(r.required_skills),
                tuple(r.preferred_skills),
                r.experience_level,
            )
            for r in rows
        ]


@settings(
    max_examples=10,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(n=integers(min_value=1, max_value=5))
def test_seed_db_idempotent_across_n_runs(n):
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)

        seed_db(engine=engine, jobs_path=_JOBS_PATH)
        after_one = _row_tuples(engine)
        assert after_one, "first seed produced no rows — jobs.json is empty?"

        for _ in range(n - 1):
            seed_db(engine=engine, jobs_path=_JOBS_PATH)

        after_n = _row_tuples(engine)
        assert after_n == after_one, (
            f"state diverged after {n} runs: "
            f"{len(after_n)} rows vs {len(after_one)} expected"
        )
    finally:
        engine.dispose()
