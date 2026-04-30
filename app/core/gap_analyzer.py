"""Gap analyzer: compare user skills against job requirements."""

from __future__ import annotations

from .models import GapResult, JobPosting, UserProfile


def analyze_gap(profile: UserProfile, job: JobPosting) -> GapResult:
    """Compare *profile* skills against *job* requirements (case-insensitive).

    Partitions into matched/missing for both required and preferred skills.
    ``match_percentage = round(matched_required / total_required * 100)``.
    If the job has 0 required skills the match percentage is 100.
    """
    user_skills_lower = {s.lower() for s in profile.skills}

    matched_required: list[str] = []
    missing_required: list[str] = []
    for skill in job.required_skills:
        if skill.lower() in user_skills_lower:
            matched_required.append(skill)
        else:
            missing_required.append(skill)

    matched_preferred: list[str] = []
    missing_preferred: list[str] = []
    for skill in job.preferred_skills:
        if skill.lower() in user_skills_lower:
            matched_preferred.append(skill)
        else:
            missing_preferred.append(skill)

    if len(job.required_skills) == 0:
        match_percentage = 100
    else:
        match_percentage = round(len(matched_required) / len(job.required_skills) * 100)

    return GapResult(
        matched_required=matched_required,
        missing_required=missing_required,
        matched_preferred=matched_preferred,
        missing_preferred=missing_preferred,
        match_percentage=match_percentage,
    )
