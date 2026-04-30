"""Data models for Skill-Bridge Career Navigator."""

from dataclasses import dataclass, field


@dataclass
class UserProfile:
    """A user's career profile with skills and experience."""

    name: str
    skills: list[str]
    experience_years: int
    education: str
    target_role: str


@dataclass
class JobPosting:
    """A synthetic job posting with required and preferred skills."""

    title: str
    description: str
    required_skills: list[str]
    preferred_skills: list[str]
    experience_level: str


@dataclass
class GapResult:
    """Result of comparing a user's skills against a job posting."""

    matched_required: list[str]
    matched_preferred: list[str]
    missing_required: list[str]
    missing_preferred: list[str]
    match_percentage: int


@dataclass
class CategorizationResult:
    """Result of AI or fallback skill categorization."""

    groups: dict[str, list[str]]
    summary: str
    is_fallback: bool


@dataclass
class LearningResource:
    """A single learning resource mapped to a skill.

    ``id`` is an optional UUID assigned by ``generate_roadmap`` so the
    API can PATCH individual resources by stable identifier. Legacy
    callers (the Streamlit UI and fixtures) omit it; the default empty
    string preserves backward compatibility.
    """

    name: str
    skill: str
    resource_type: str
    estimated_hours: int
    url: str
    completed: bool = False
    id: str = ""


@dataclass
class RoadmapPhase:
    """A time-based phase in the learning roadmap."""

    label: str
    resources: list[LearningResource] = field(default_factory=list)


@dataclass
class Roadmap:
    """A phased learning roadmap."""

    phases: list[RoadmapPhase]
