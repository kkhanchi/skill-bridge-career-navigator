"""Unit tests for the jobs seed script.

Uses an in-memory SQLite engine so the tests are fast and isolated.
Schema is applied via Base.metadata.create_all (Alembic correctness
is covered separately in test_alembic_smoke.py).

Requirement reference: R5.1, R5.2, R5.3, R5.4, R5.5, R5.6.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.job_catalog import load_jobs
from app.db.base import Base
from app.db.models import JobORM, ProfileORM
from app.repositories.job_repo import InMemoryJobRepository
from scripts.seed_db import seed_db


_PKG_ROOT = Path(__file__).resolve().parents[2]
_JOBS_PATH = str(_PKG_ROOT / "data" / "jobs.json")


@pytest.fixture
def sql_engine():
    """In-memory SQLite engine with schema applied."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def jobs_file(tmp_path):
    """Copy data/jobs.json to a temp path so tests can mutate it."""
    target = tmp_path / "jobs.json"
    target.write_text(Path(_JOBS_PATH).read_text(encoding="utf-8"), encoding="utf-8")
    return str(target)


def _all_jobs(engine) -> list[JobORM]:
    with Session(engine) as session:
        return list(session.scalars(select(JobORM).order_by(JobORM.id.asc())).all())


def test_seed_db_populates_jobs_table(sql_engine, jobs_file):
    # R5.1: seed_db reads the file and upserts one row per job.
    count = seed_db(engine=sql_engine, jobs_path=jobs_file)

    source_jobs = load_jobs(jobs_file)
    assert count == len(source_jobs)

    rows = _all_jobs(sql_engine)
    assert len(rows) == len(source_jobs)


def test_seed_db_ids_match_in_memory_repository(sql_engine, jobs_file):
    # R5.4: slug stability — seed_db produces the same ids as
    # InMemoryJobRepository for the same input.
    seed_db(engine=sql_engine, jobs_path=jobs_file)

    source_jobs = load_jobs(jobs_file)
    memory_repo = InMemoryJobRepository(source_jobs)
    # Pull out ids via the repo's private records in load order.
    expected_ids = {rec.id for rec in memory_repo._records}
    actual_ids = {row.id for row in _all_jobs(sql_engine)}
    assert actual_ids == expected_ids


def test_seed_db_is_idempotent_across_runs(sql_engine, jobs_file):
    # R5.2: running N times produces the same final state as running once.
    first_count = seed_db(engine=sql_engine, jobs_path=jobs_file)
    rows_after_first = _all_jobs(sql_engine)

    second_count = seed_db(engine=sql_engine, jobs_path=jobs_file)
    rows_after_second = _all_jobs(sql_engine)

    # Row count is stable.
    assert len(rows_after_first) == len(rows_after_second)
    # Both runs report touching the same number of jobs.
    assert first_count == second_count
    # Tuple of (id, title, description, required, preferred, level)
    # is invariant across runs.
    def _tuple(r: JobORM) -> tuple:
        return (
            r.id, r.title, r.description,
            tuple(r.required_skills), tuple(r.preferred_skills),
            r.experience_level,
        )
    assert [_tuple(r) for r in rows_after_first] == [_tuple(r) for r in rows_after_second]


def test_seed_db_updates_content_fields_but_keeps_id_stable(sql_engine, tmp_path):
    # R5.3: if jobs.json content changes for an existing slug, the
    # content refreshes but the slug itself does not change.
    jobs_path = tmp_path / "jobs.json"
    original = [
        {
            "title": "Backend Developer",
            "description": "Original description",
            "required_skills": ["Python"],
            "preferred_skills": [],
            "experience_level": "Mid",
        }
    ]
    jobs_path.write_text(json.dumps(original), encoding="utf-8")

    seed_db(engine=sql_engine, jobs_path=str(jobs_path))

    original_rows = _all_jobs(sql_engine)
    assert len(original_rows) == 1
    assert original_rows[0].id == "backend-developer"
    assert original_rows[0].description == "Original description"

    # Change description, re-seed.
    updated = [dict(original[0])]
    updated[0]["description"] = "Updated description"
    jobs_path.write_text(json.dumps(updated), encoding="utf-8")

    seed_db(engine=sql_engine, jobs_path=str(jobs_path))

    updated_rows = _all_jobs(sql_engine)
    assert len(updated_rows) == 1
    # Slug is stable — same id as before.
    assert updated_rows[0].id == "backend-developer"
    # Content refreshed.
    assert updated_rows[0].description == "Updated description"


def test_seed_db_only_touches_jobs_table(sql_engine, jobs_file):
    # R5.5: seed_db must not write to users, profiles, analyses,
    # roadmaps, or any taxonomy/resources tables.
    seed_db(engine=sql_engine, jobs_path=jobs_file)

    with Session(sql_engine) as session:
        # profiles exists in the schema but seed_db never touches it.
        profile_count = session.scalar(select(ProfileORM.id).limit(1))
        assert profile_count is None


def test_seed_db_rolls_back_on_failure(sql_engine, tmp_path, monkeypatch):
    # R5.6: a partial failure commits nothing — safe to re-attempt.
    # Simulate a crash mid-loop by monkeypatching session.add on the
    # second call.
    jobs_path = tmp_path / "jobs.json"
    jobs_path.write_text(json.dumps([
        {
            "title": "A",
            "description": "d",
            "required_skills": [],
            "preferred_skills": [],
            "experience_level": "Mid",
        },
        {
            "title": "B",
            "description": "d",
            "required_skills": [],
            "preferred_skills": [],
            "experience_level": "Mid",
        },
    ]), encoding="utf-8")

    from sqlalchemy.orm import Session as _Session

    original_add = _Session.add
    call_count = {"n": 0}

    def flaky_add(self, instance, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("boom")
        return original_add(self, instance, *args, **kwargs)

    monkeypatch.setattr(_Session, "add", flaky_add)

    with pytest.raises(RuntimeError, match="boom"):
        seed_db(engine=sql_engine, jobs_path=str(jobs_path))

    # Table is empty — the first successful add was rolled back with
    # the rest (single-transaction guarantee).
    assert _all_jobs(sql_engine) == []
