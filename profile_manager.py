"""Profile management: creation, validation, update, and session persistence."""

from __future__ import annotations

from models import UserProfile


def _deduplicate_skills(skills: list[str]) -> tuple[list[str], bool]:
    """Remove duplicate skills (case-insensitive). Returns (deduped list, had_duplicates)."""
    seen: set[str] = set()
    unique: list[str] = []
    for skill in skills:
        key = skill.strip().lower()
        if key not in seen:
            seen.add(key)
            unique.append(skill.strip())
    return unique, len(unique) < len(skills)


def create_profile(
    name: str,
    skills: list[str],
    experience_years: int,
    education: str,
    target_role: str,
) -> tuple[UserProfile, str | None]:
    """Validate inputs and return (UserProfile, notification_message).

    The second element is a string like "Duplicate skills have been removed"
    when duplicates were auto-removed, or ``None`` otherwise.

    Raises ``ValueError`` with a specific message for each validation failure.
    """
    # --- required-field checks ---
    if not name or not isinstance(name, str) or not name.strip():
        raise ValueError("Name is required")
    if not target_role or not isinstance(target_role, str) or not target_role.strip():
        raise ValueError("Target role is required")
    if not isinstance(skills, list):
        raise ValueError("Skills must be a list")
    if len(skills) == 0:
        raise ValueError("Skills are required")

    # --- per-skill validation (before dedup) ---
    for skill in skills:
        if not isinstance(skill, str) or not skill.strip():
            raise ValueError("Each skill must be a non-empty string")
        if len(skill.strip()) > 100:
            raise ValueError("Skill name must be 100 characters or fewer")

    # --- deduplication ---
    deduped, had_dupes = _deduplicate_skills(skills)

    # --- count validation (after dedup) ---
    if len(deduped) < 1:
        raise ValueError("Profile must have between 1 and 30 skills")
    if len(deduped) > 30:
        raise ValueError("Profile must have between 1 and 30 skills")

    notification: str | None = None
    if had_dupes:
        notification = "Duplicate skills have been removed"

    profile = UserProfile(
        name=name.strip(),
        skills=deduped,
        experience_years=experience_years,
        education=education.strip(),
        target_role=target_role.strip(),
    )
    return profile, notification


def update_profile(
    profile: UserProfile,
    added_skills: list[str] | None = None,
    removed_skills: list[str] | None = None,
) -> UserProfile:
    """Return a new UserProfile with skills added/removed.

    Raises ``ValueError`` if the resulting skill list is invalid.
    """
    current = list(profile.skills)

    # Add new skills
    if added_skills:
        existing_lower = {s.lower() for s in current}
        for skill in added_skills:
            s = skill.strip()
            if s and s.lower() not in existing_lower:
                current.append(s)
                existing_lower.add(s.lower())

    # Remove specified skills (case-insensitive)
    if removed_skills:
        remove_lower = {s.strip().lower() for s in removed_skills if s.strip()}
        current = [s for s in current if s.lower() not in remove_lower]

    # Validate resulting list
    for skill in current:
        if len(skill) > 100:
            raise ValueError("Skill name must be 100 characters or fewer")
    if len(current) < 1:
        raise ValueError("Profile must have between 1 and 30 skills")
    if len(current) > 30:
        raise ValueError("Profile must have between 1 and 30 skills")

    return UserProfile(
        name=profile.name,
        skills=current,
        experience_years=profile.experience_years,
        education=profile.education,
        target_role=profile.target_role,
    )


def save_profile(profile: UserProfile) -> None:
    """Persist profile to ``st.session_state``. Imports streamlit lazily."""
    import streamlit as st
    st.session_state["user_profile"] = profile


def load_profile() -> UserProfile | None:
    """Load profile from ``st.session_state``, or ``None`` if not found."""
    import streamlit as st
    return st.session_state.get("user_profile", None)
