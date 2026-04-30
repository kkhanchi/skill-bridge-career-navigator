"""Shared test fixtures for Skill-Bridge Career Navigator."""

import sys
import os
import pytest

# Add parent directory to path so modules can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import UserProfile, JobPosting, LearningResource


@pytest.fixture
def sample_profile():
    return UserProfile(
        name="Jane Doe",
        skills=["Python", "SQL", "Git"],
        experience_years=2,
        education="Bachelor's",
        target_role="Backend Developer",
    )


@pytest.fixture
def sample_job():
    return JobPosting(
        title="Backend Developer",
        description="Build scalable APIs",
        required_skills=["Python", "SQL", "REST APIs", "Git"],
        preferred_skills=["Docker", "AWS", "Redis"],
        experience_level="Mid",
    )


@pytest.fixture
def sample_taxonomy():
    return [
        "Python", "Java", "JavaScript", "SQL", "REST APIs", "Git",
        "Docker", "AWS", "Redis", "React", "Machine Learning",
    ]


@pytest.fixture
def sample_resources():
    return [
        LearningResource(name="REST API Course", skill="REST APIs",
                         resource_type="course", estimated_hours=12,
                         url="https://example.com/rest"),
        LearningResource(name="Docker Essentials", skill="Docker",
                         resource_type="course", estimated_hours=12,
                         url="https://example.com/docker"),
        LearningResource(name="AWS Cloud Practitioner", skill="AWS",
                         resource_type="certification", estimated_hours=25,
                         url="https://example.com/aws"),
        LearningResource(name="Redis Caching", skill="Redis",
                         resource_type="course", estimated_hours=8,
                         url="https://example.com/redis"),
    ]

# ---------------------------------------------------------------------------
# Flask integration fixtures (added in Phase 1 / Stage B).
#
# Each integration test gets a fresh ``create_app("test")`` instance so
# in-memory repositories stay isolated across tests (R10.2).
# ---------------------------------------------------------------------------

from app import create_app


@pytest.fixture
def app():
    """Build a fresh Flask app configured for tests (TestConfig)."""
    return create_app("test")


@pytest.fixture
def client(app):
    """Flask test client bound to the per-test app instance."""
    return app.test_client()
