"""Unit tests for gap analysis — happy path and edge case."""

from models import UserProfile, JobPosting
from gap_analyzer import analyze_gap


def test_happy_path_gap_analysis(sample_profile, sample_job):
    """Happy path: profile with some skills → correct missing skills identified."""
    result = analyze_gap(sample_profile, sample_job)

    # Python, SQL, Git are matched; REST APIs is missing
    assert set(result.matched_required) == {"Python", "SQL", "Git"}
    assert set(result.missing_required) == {"REST APIs"}
    assert result.match_percentage == 75  # 3/4 = 75%

    # Preferred: none matched (profile has no Docker/AWS/Redis)
    assert set(result.missing_preferred) == {"Docker", "AWS", "Redis"}
    assert result.matched_preferred == []


def test_edge_case_zero_skills(sample_job):
    """Edge case: profile with zero skills → all required skills missing."""
    empty_profile = UserProfile(
        name="Empty User",
        skills=[],
        experience_years=0,
        education="High School",
        target_role="Backend Developer",
    )
    result = analyze_gap(empty_profile, sample_job)

    assert set(result.missing_required) == set(sample_job.required_skills)
    assert result.matched_required == []
    assert result.match_percentage == 0


def test_full_match():
    """Profile with all required skills → 100% match."""
    profile = UserProfile(
        name="Pro Dev",
        skills=["Python", "SQL", "REST APIs", "Git"],
        experience_years=5,
        education="Master's",
        target_role="Backend Developer",
    )
    job = JobPosting(
        title="Backend Developer",
        description="Build APIs",
        required_skills=["Python", "SQL", "REST APIs", "Git"],
        preferred_skills=["Docker"],
        experience_level="Mid",
    )
    result = analyze_gap(profile, job)
    assert result.match_percentage == 100
    assert result.missing_required == []
