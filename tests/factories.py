"""factory-boy factories for the Phase 2/3 ORM models.

One factory per ORM model (6 total). Each factory produces a DB-
insertable instance with all NOT NULL fields populated by realistic
values (via Faker) and FK parents auto-created by SubFactory unless
the caller passes one explicitly.

Design notes
------------

- **`factory.Factory`**, not `factory.alchemy.SQLAlchemyModelFactory`.
  The suite runs against both the in-memory and SQL backends. A
  SQLAlchemy model factory would require a bound session at
  construction time, which would collide with the memory-backed
  tests. Plain `factory.Factory` produces detached ORM instances;
  the test chooses whether to ``session.add()`` them.
- **`factory.Sequence` for unique email** — each UserFactory call
  produces a fresh number, guaranteeing uniqueness across a test
  run. Prevents accidental collisions with the UNIQUE constraint on
  ``users.email``.
- **`factory.SubFactory(UserFactory)`** on child models that carry a
  NOT NULL FK — the parent row is built automatically unless the
  caller passes ``user=existing_user``. Tests that want to reuse a
  single user across many rows pass the existing user explicitly.
- **Password hash is a fake fixed string** — factories MUST stay
  fast; a real argon2 hash at production cost params would add
  ~50ms per factory call. The stub value is a valid argon2id
  encoded string shape but will never verify against any password.

Requirement reference: R7.1, R7.2, R7.3, R7.4, R7.6.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import factory
from faker import Faker

from app.db.models import (
    AnalysisORM,
    JobORM,
    ProfileORM,
    RefreshTokenORM,
    RoadmapORM,
    UserORM,
)

fake = Faker()

# A valid argon2id shape. Never verifies against a real password —
# tests that need to verify auth should use the real hasher via the
# authenticated_client fixture, not a factory-produced hash.
_FAKE_ARGON2_HASH = "$argon2id$v=19$m=8,t=1,p=1$c2FsdHNhbHRzYWx0$dGVzdGluZ3Rlc3Rpbmc"


# ---------------------------------------------------------------------------
# UserFactory
# ---------------------------------------------------------------------------


class UserFactory(factory.Factory):  # type: ignore[misc]
    """Detached UserORM with unique email + fake password hash."""

    class Meta:
        model = UserORM

    id = factory.LazyFunction(lambda: uuid4().hex)
    # Sequence guarantees uniqueness across a test run. Starts at 0.
    email = factory.Sequence(lambda n: f"factory-user-{n}@example.com")
    password_hash = _FAKE_ARGON2_HASH
    created_at = factory.LazyFunction(lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# JobFactory
# ---------------------------------------------------------------------------


class JobFactory(factory.Factory):  # type: ignore[misc]
    """Detached JobORM with slug-derived id."""

    class Meta:
        model = JobORM

    # Slug id aligns with how InMemoryJobRepository produces them.
    id = factory.Sequence(lambda n: f"factory-job-{n}")
    title = factory.Faker("job")
    description = factory.Faker("paragraph", nb_sentences=3)
    # Minimal but valid skill lists. Tests wanting specific content
    # override explicitly.
    required_skills = factory.LazyFunction(lambda: ["Python", "SQL"])
    preferred_skills = factory.LazyFunction(lambda: ["Docker"])
    experience_level = factory.Faker("random_element", elements=["Junior", "Mid", "Senior"])


# ---------------------------------------------------------------------------
# ProfileFactory
# ---------------------------------------------------------------------------


class ProfileFactory(factory.Factory):  # type: ignore[misc]
    """Detached ProfileORM; auto-creates a parent UserORM unless passed in."""

    class Meta:
        model = ProfileORM

    id = factory.LazyFunction(lambda: uuid4().hex)
    # The NOT NULL FK. Auto-create a parent if the caller doesn't
    # pass one; callers that want to reuse an existing user do so as
    # ``ProfileFactory(user_id=existing_user.id)``.
    user_id = factory.LazyAttribute(lambda o: o.user.id if hasattr(o, "user") else uuid4().hex)
    user = factory.SubFactory(UserFactory)
    name = factory.Faker("name")
    skills = factory.LazyFunction(lambda: ["Python", "SQL", "Git"])
    experience_years = factory.Faker("random_int", min=0, max=20)
    education = factory.Faker(
        "random_element",
        elements=["High School", "Bachelor's", "Master's", "PhD"],
    )
    target_role = factory.Faker("job")
    created_at = factory.LazyFunction(lambda: datetime.now(UTC))
    updated_at = factory.LazyAttribute(lambda o: o.created_at)

    class Params:
        # Hide the ``user`` attribute from the ORM constructor —
        # it's a factory-only relationship used to derive user_id.
        # Without this, factory-boy would try to pass user= to
        # ProfileORM.__init__ which doesn't accept it.
        pass

    @classmethod
    def _create(cls, model_class, *args, **kwargs):  # type: ignore[no-untyped-def]
        # Strip the internal 'user' keyword before hitting the model
        # constructor. SubFactory populated it so user_id is already
        # stamped; user itself isn't an ORM field.
        kwargs.pop("user", None)
        return model_class(*args, **kwargs)

    @classmethod
    def _build(cls, model_class, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.pop("user", None)
        return model_class(*args, **kwargs)


# ---------------------------------------------------------------------------
# AnalysisFactory
# ---------------------------------------------------------------------------


class AnalysisFactory(factory.Factory):  # type: ignore[misc]
    """Detached AnalysisORM with user_id + job_id FKs.

    profile_id is nullable (analyses survive profile deletion per the
    Phase 2 FK cascade); factories default it to None. Tests that
    want a profile link build a ProfileFactory separately and pass
    ``profile_id=profile.id``.
    """

    class Meta:
        model = AnalysisORM

    id = factory.LazyFunction(lambda: uuid4().hex)
    user = factory.SubFactory(UserFactory)
    user_id = factory.LazyAttribute(lambda o: o.user.id)
    job = factory.SubFactory(JobFactory)
    job_id = factory.LazyAttribute(lambda o: o.job.id)
    profile_id = None
    result = factory.LazyFunction(
        lambda: {
            "gap": {
                "matched_required": ["Python"],
                "missing_required": ["SQL"],
                "matched_preferred": [],
                "missing_preferred": [],
                "match_percentage": 50,
            },
            "categorization": {
                "groups": {"Programming": ["SQL"]},
                "summary": "Factory-generated analysis.",
                "is_fallback": True,
            },
        }
    )
    created_at = factory.LazyFunction(lambda: datetime.now(UTC))

    @classmethod
    def _create(cls, model_class, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.pop("user", None)
        kwargs.pop("job", None)
        return model_class(*args, **kwargs)

    @classmethod
    def _build(cls, model_class, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.pop("user", None)
        kwargs.pop("job", None)
        return model_class(*args, **kwargs)


# ---------------------------------------------------------------------------
# RoadmapFactory
# ---------------------------------------------------------------------------


class RoadmapFactory(factory.Factory):  # type: ignore[misc]
    """Detached RoadmapORM with an AnalysisFactory-backed analysis_id."""

    class Meta:
        model = RoadmapORM

    id = factory.LazyFunction(lambda: uuid4().hex)
    analysis = factory.SubFactory(AnalysisFactory)
    analysis_id = factory.LazyAttribute(lambda o: o.analysis.id)
    phases = factory.LazyFunction(
        lambda: [
            {
                "label": "Month 1-2",
                "resources": [
                    {
                        "id": uuid4().hex,
                        "name": "SQL Course",
                        "skill": "SQL",
                        "resource_type": "course",
                        "estimated_hours": 10,
                        "url": "https://example.com/sql",
                        "completed": False,
                    }
                ],
            }
        ]
    )
    created_at = factory.LazyFunction(lambda: datetime.now(UTC))
    updated_at = factory.LazyAttribute(lambda o: o.created_at)

    @classmethod
    def _create(cls, model_class, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.pop("analysis", None)
        return model_class(*args, **kwargs)

    @classmethod
    def _build(cls, model_class, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.pop("analysis", None)
        return model_class(*args, **kwargs)


# ---------------------------------------------------------------------------
# RefreshTokenFactory
# ---------------------------------------------------------------------------


class RefreshTokenFactory(factory.Factory):  # type: ignore[misc]
    """Detached RefreshTokenORM with a 14-day expiry and fresh jti."""

    class Meta:
        model = RefreshTokenORM

    id = factory.LazyFunction(lambda: uuid4().hex)
    user = factory.SubFactory(UserFactory)
    user_id = factory.LazyAttribute(lambda o: o.user.id)
    jti = factory.LazyFunction(lambda: uuid4().hex)
    expires_at = factory.LazyFunction(lambda: datetime.now(UTC) + timedelta(days=14))
    revoked_at = None
    created_at = factory.LazyFunction(lambda: datetime.now(UTC))

    @classmethod
    def _create(cls, model_class, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.pop("user", None)
        return model_class(*args, **kwargs)

    @classmethod
    def _build(cls, model_class, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.pop("user", None)
        return model_class(*args, **kwargs)
