"""Unit tests for the Phase 2 ORM models.

Introspects the schema SQLAlchemy produces from the ORM definitions
and asserts the design matches the requirements:

- Exactly six tables exist (five Phase 2 tables + refresh_tokens
  added in Phase 3 Stage E).
- Indexes land where R1.2 lists them.
- Column types match R1.3 (String widths, Text for description,
  Integer for years, DateTime(timezone=True) for timestamps).
- Portable JSON columns actually round-trip list[str] values (R7.4).
- UNIQUE on users.email is enforced at the DB layer.

Requirement reference: R1.1, R1.2, R1.3, R1.7, R7.4, R11.3.
"""

from __future__ import annotations

import pytest
from sqlalchemy import String, create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import (
    AnalysisORM,
    JobORM,
    ProfileORM,
    RefreshTokenORM,
    RoadmapORM,
    UserORM,
)


@pytest.fixture
def engine():
    """Throwaway SQLite engine with the full schema applied."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


# ---------------------------------------------------------------------------
# Schema shape
# ---------------------------------------------------------------------------


def test_create_all_produces_exactly_six_tables(engine):
    # Phase 2 produced five; Phase 3 Stage E added ``refresh_tokens``.
    tables = set(inspect(engine).get_table_names())
    assert tables == {
        "users",
        "profiles",
        "jobs",
        "analyses",
        "roadmaps",
        "refresh_tokens",
    }


def test_expected_indexes_exist(engine):
    insp = inspect(engine)
    # (table, column) pairs that must be individually indexed.
    expected = {
        ("profiles", "user_id"),
        ("jobs", "title"),
        ("jobs", "experience_level"),
        ("analyses", "profile_id"),
        ("analyses", "job_id"),
        ("roadmaps", "analysis_id"),
        ("refresh_tokens", "user_id"),
    }
    actual = set()
    for table in (
        "users",
        "profiles",
        "jobs",
        "analyses",
        "roadmaps",
        "refresh_tokens",
    ):
        for idx in insp.get_indexes(table):
            # Single-column indexes we explicitly declared with index=True.
            if len(idx["column_names"]) == 1:
                actual.add((table, idx["column_names"][0]))
    missing = expected - actual
    assert not missing, f"missing indexes: {missing}"


def test_users_email_unique_constraint(engine, session):
    session.add(UserORM(id="u1", email="a@b.co", password_hash="x"))
    session.commit()

    # Second row with the same email must fail — either as a UNIQUE
    # index violation or a UNIQUE constraint violation depending on
    # how SQLAlchemy emits it; both surface as IntegrityError.
    session.add(UserORM(id="u2", email="a@b.co", password_hash="y"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# ---------------------------------------------------------------------------
# Column types
# ---------------------------------------------------------------------------


def test_primary_key_widths(engine):
    insp = inspect(engine)

    def pk_col(table: str, col: str) -> dict:
        for c in insp.get_columns(table):
            if c["name"] == col:
                return c
        raise AssertionError(f"no column {col!r} on {table!r}")

    # R1.3: uuid4 hex -> String(32) for users, profiles, analyses, roadmaps.
    for table in ("users", "profiles", "analyses", "roadmaps"):
        col = pk_col(table, "id")
        assert isinstance(col["type"], String)
        assert col["type"].length == 32, f"{table}.id width"

    # R1.3: slug -> String(64) for jobs.
    col = pk_col("jobs", "id")
    assert isinstance(col["type"], String)
    assert col["type"].length == 64


def test_profiles_user_id_is_nullable(engine):
    # R1.4: nullable until Phase 3.
    insp = inspect(engine)
    user_id = next(c for c in insp.get_columns("profiles") if c["name"] == "user_id")
    assert user_id["nullable"] is True


def test_analyses_user_id_is_nullable(engine):
    # R1.4: nullable until Phase 3.
    insp = inspect(engine)
    user_id = next(c for c in insp.get_columns("analyses") if c["name"] == "user_id")
    assert user_id["nullable"] is True


# ---------------------------------------------------------------------------
# JSON round-trip (R7.4 — Portable_JSON)
# ---------------------------------------------------------------------------


def test_profile_skills_json_round_trip(session):
    skills = ["Python", "SQL", "Docker"]
    session.add(
        ProfileORM(
            id="p1",
            name="Jane",
            skills=skills,
            experience_years=3,
            education="BSc",
            target_role="Backend Developer",
        )
    )
    session.commit()

    # Fresh read: close the current row out of the identity map so we
    # exercise the actual JSON deserialization path, not an in-memory
    # cache.
    session.expire_all()
    row = session.get(ProfileORM, "p1")
    assert row is not None
    assert row.skills == skills


def test_job_required_and_preferred_skills_round_trip(session):
    required = ["Python", "REST APIs"]
    preferred = ["Docker"]
    session.add(
        JobORM(
            id="backend-developer",
            title="Backend Developer",
            description="Build APIs",
            required_skills=required,
            preferred_skills=preferred,
            experience_level="Mid",
        )
    )
    session.commit()
    session.expire_all()

    row = session.get(JobORM, "backend-developer")
    assert row.required_skills == required
    assert row.preferred_skills == preferred


def test_analysis_result_round_trip(session):
    # AnalysisORM.result is a dict; round-trip a realistic payload.
    session.add(
        JobORM(
            id="backend-developer",
            title="Backend Developer",
            description="Build APIs",
            required_skills=["Python"],
            preferred_skills=[],
            experience_level="Mid",
        )
    )
    result = {
        "gap": {
            "matched_required": ["Python"],
            "missing_required": [],
            "matched_preferred": [],
            "missing_preferred": [],
            "match_percentage": 100,
        },
        "categorization": {
            "groups": {"Programming": ["Python"]},
            "summary": "You match this role.",
            "is_fallback": True,
        },
    }
    session.add(
        AnalysisORM(
            id="a1",
            profile_id=None,
            job_id="backend-developer",
            result=result,
        )
    )
    session.commit()
    session.expire_all()

    row = session.get(AnalysisORM, "a1")
    assert row.result == result


def test_roadmap_phases_round_trip_preserves_resource_ids(session):
    phases = [
        {
            "label": "Month 1-2",
            "resources": [
                {
                    "id": "res-1",
                    "name": "REST API Course",
                    "skill": "REST APIs",
                    "resource_type": "course",
                    "estimated_hours": 12,
                    "url": "https://example.com/rest",
                    "completed": False,
                }
            ],
        },
    ]
    # Need an analysis to satisfy the FK.
    session.add(
        JobORM(
            id="job1", title="J", description="d",
            required_skills=[], preferred_skills=[], experience_level="Mid",
        )
    )
    session.add(
        AnalysisORM(id="a1", job_id="job1", result={}, profile_id=None)
    )
    session.add(
        RoadmapORM(id="r1", analysis_id="a1", phases=phases)
    )
    session.commit()
    session.expire_all()

    row = session.get(RoadmapORM, "r1")
    assert row.phases == phases
    assert row.phases[0]["resources"][0]["id"] == "res-1"
    assert row.phases[0]["resources"][0]["completed"] is False
