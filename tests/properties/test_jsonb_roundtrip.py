"""Portable_JSON round-trip property (R7.4).

For any list of strings, INSERTing it into a JSON-bearing column and
SELECTing it back through a fresh session produces an element-wise
equal list. Exercises the ``JSON().with_variant(JSONB(), "postgresql")``
type on the SQLite side; the Postgres side is covered structurally by
the model definition + Alembic smoke test.

Property 5: Portable_JSON round-trip equality — Validates R7.4.
"""

from __future__ import annotations

from uuid import uuid4

from hypothesis import HealthCheck, given, settings
from hypothesis.strategies import lists, text
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import ProfileORM


@settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(
    skills=lists(
        text(min_size=1, max_size=100).filter(lambda s: s.strip() != ""),
        min_size=0,
        max_size=30,
    ),
)
def test_skills_json_round_trip(skills):
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        profile_id = uuid4().hex

        # Write in one session.
        with Session(engine) as session:
            session.add(
                ProfileORM(
                    id=profile_id,
                    name="Test",
                    skills=list(skills),
                    experience_years=0,
                    education="",
                    target_role="R",
                )
            )
            session.commit()

        # Read in a fresh session — forces the JSON deserialization
        # path rather than returning an in-memory cached object.
        with Session(engine) as session:
            row = session.get(ProfileORM, profile_id)
            assert row is not None
            assert row.skills == list(skills)
    finally:
        engine.dispose()
