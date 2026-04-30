"""Round-trip tests for tests/factories.py (Phase 4 P5 property).

For each factory, assert that the produced instance:
  1. Is DB-insertable (session.add + session.commit doesn't raise).
  2. Survives a session.expire_all() -> session.get() round-trip
     with field equality.

This is the concrete-test incarnation of requirement P5: factory-
produced ORM instances MUST survive the SQLAlchemy identity map's
reload path with byte-for-byte equal field values.

Requirement reference: R7.1, R7.2 (P5).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
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
from tests.factories import (
    AnalysisFactory,
    JobFactory,
    ProfileFactory,
    RefreshTokenFactory,
    RoadmapFactory,
    UserFactory,
)

# ---------------------------------------------------------------------------
# Throwaway engine + session per test
# ---------------------------------------------------------------------------


@pytest.fixture
def factory_session():
    """A fresh sqlite:///:memory: engine + Session for one test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# One round-trip per factory
# ---------------------------------------------------------------------------


def test_user_factory_round_trip(factory_session):
    user = UserFactory.build()
    factory_session.add(user)
    factory_session.commit()
    factory_session.expire_all()

    row = factory_session.get(UserORM, user.id)
    assert row is not None
    assert row.email == user.email
    assert row.password_hash == user.password_hash


def test_job_factory_round_trip(factory_session):
    job = JobFactory.build()
    factory_session.add(job)
    factory_session.commit()
    factory_session.expire_all()

    row = factory_session.get(JobORM, job.id)
    assert row is not None
    assert row.title == job.title
    assert row.required_skills == job.required_skills


def test_profile_factory_round_trip(factory_session):
    # ProfileFactory's SubFactory(UserFactory) auto-creates the owner.
    # Both rows must land in the DB, so we add both explicitly.
    profile = ProfileFactory.build()
    # The factory's user_id points at a user id that doesn't exist in
    # this session yet — seed it first to satisfy the FK.
    factory_session.add(UserORM(id=profile.user_id, email="p-owner@example.com", password_hash="x"))
    factory_session.add(profile)
    factory_session.commit()
    factory_session.expire_all()

    row = factory_session.get(ProfileORM, profile.id)
    assert row is not None
    assert row.name == profile.name
    assert row.skills == profile.skills
    assert row.user_id == profile.user_id


def test_analysis_factory_round_trip(factory_session):
    analysis = AnalysisFactory.build()
    # Seed the FK parents.
    factory_session.add(
        UserORM(id=analysis.user_id, email="a-owner@example.com", password_hash="x")
    )
    factory_session.add(
        JobORM(
            id=analysis.job_id,
            title="Factory Test Job",
            description="Factory Test Job description",
            required_skills=["Python"],
            preferred_skills=[],
            experience_level="Mid",
        )
    )
    factory_session.add(analysis)
    factory_session.commit()
    factory_session.expire_all()

    row = factory_session.get(AnalysisORM, analysis.id)
    assert row is not None
    assert row.user_id == analysis.user_id
    assert row.job_id == analysis.job_id
    assert row.result["gap"]["match_percentage"] == 50


def test_roadmap_factory_round_trip(factory_session):
    roadmap = RoadmapFactory.build()
    # Seed the chain: user -> job -> analysis before the roadmap.
    # Because RoadmapFactory.analysis is a SubFactory but we stripped
    # it from the model constructor, we manually assemble a valid FK
    # chain pointing at the roadmap's analysis_id.
    factory_session.add(
        UserORM(id="roadmap-owner", email="rm-owner@example.com", password_hash="x")
    )
    factory_session.add(
        JobORM(
            id="roadmap-job",
            title="Roadmap Test Job",
            description="Roadmap Test Job description",
            required_skills=[],
            preferred_skills=[],
            experience_level="Mid",
        )
    )
    factory_session.add(
        AnalysisORM(
            id=roadmap.analysis_id,
            user_id="roadmap-owner",
            job_id="roadmap-job",
            result={},
        )
    )
    factory_session.add(roadmap)
    factory_session.commit()
    factory_session.expire_all()

    row = factory_session.get(RoadmapORM, roadmap.id)
    assert row is not None
    assert row.analysis_id == roadmap.analysis_id
    assert len(row.phases) == 1
    assert row.phases[0]["label"] == "Month 1-2"


def test_refresh_token_factory_round_trip(factory_session):
    token = RefreshTokenFactory.build()
    factory_session.add(UserORM(id=token.user_id, email="tok-owner@example.com", password_hash="x"))
    factory_session.add(token)
    factory_session.commit()
    factory_session.expire_all()

    row = factory_session.get(RefreshTokenORM, token.id)
    assert row is not None
    assert row.user_id == token.user_id
    assert row.jti == token.jti
    assert row.revoked_at is None
