"""Profile printer: format a UserProfile as human-readable text."""

from __future__ import annotations

from .models import UserProfile


def format_profile(profile: UserProfile) -> str:
    """Format *profile* as readable text.

    The output includes name, skills, experience, education, and target role.
    Skills are listed so that ``parse_resume(format_profile(p), taxonomy)``
    produces a superset of the original skill set (round-trip property).
    """
    skills_str = ", ".join(profile.skills)
    lines = [
        f"Name: {profile.name}",
        f"Skills: {skills_str}",
        f"Experience: {profile.experience_years} years",
        f"Education: {profile.education}",
        f"Target Role: {profile.target_role}",
    ]
    return "\n".join(lines)
