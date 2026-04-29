"""Roadmap generator: build phased learning plans from gap results."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from uuid import uuid4

from .models import (
    GapResult,
    JobPosting,
    LearningResource,
    Roadmap,
    RoadmapPhase,
    UserProfile,
)

_PHASE_LABELS = ["Month 1-2", "Month 3-4", "Month 5-6"]


def _load_resources(path: str = "data/learning_resources.json") -> list[LearningResource]:
    """Load learning resources from JSON."""
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [
        LearningResource(
            name=r["name"],
            skill=r["skill"],
            resource_type=r["resource_type"],
            estimated_hours=r["estimated_hours"],
            url=r["url"],
            completed=r.get("completed", False),
        )
        for r in raw
    ]


def generate_roadmap(
    gap: GapResult,
    resources: list[LearningResource],
) -> Roadmap:
    """Map missing skills to resources across 3 phases.

    Required-missing skills are placed in earlier phases;
    preferred-missing skills in later phases.
    """
    phases = [RoadmapPhase(label=label, resources=[]) for label in _PHASE_LABELS]

    # Build a lookup: skill (lower) -> list of resources
    resource_map: dict[str, list[LearningResource]] = {}
    for r in resources:
        resource_map.setdefault(r.skill.lower(), []).append(r)

    # Collect ordered missing skills: required first, then preferred
    ordered_skills: list[str] = list(gap.missing_required) + list(gap.missing_preferred)

    if not ordered_skills:
        return Roadmap(phases=phases)

    # Distribute skills across phases as evenly as possible
    # Required skills go to earlier phases, preferred to later
    n_required = len(gap.missing_required)

    for idx, skill in enumerate(ordered_skills):
        # Determine phase: required skills in phases 0-1, preferred in phases 1-2
        if idx < n_required:
            # Spread required skills across phase 0 and 1
            if n_required <= 2:
                phase_idx = 0
            else:
                phase_idx = 0 if idx < (n_required + 1) // 2 else 1
        else:
            # Preferred skills go to phase 1 or 2
            pref_idx = idx - n_required
            n_preferred = len(gap.missing_preferred)
            if n_preferred <= 2:
                phase_idx = 2
            else:
                phase_idx = 1 if pref_idx < (n_preferred + 1) // 2 else 2

        # Find matching resources for this skill
        skill_resources = resource_map.get(skill.lower(), [])
        if skill_resources:
            for r in skill_resources:
                phases[phase_idx].resources.append(
                    LearningResource(
                        name=r.name,
                        skill=r.skill,
                        resource_type=r.resource_type,
                        estimated_hours=r.estimated_hours,
                        url=r.url,
                        completed=False,
                        id=uuid4().hex,
                    )
                )
        else:
            # Create a placeholder resource
            phases[phase_idx].resources.append(
                LearningResource(
                    name=f"Learn {skill}",
                    skill=skill,
                    resource_type="course",
                    estimated_hours=10,
                    url=f"https://example.com/learn-{skill.lower().replace(' ', '-')}",
                    completed=False,
                    id=uuid4().hex,
                )
            )

    return Roadmap(phases=phases)


def mark_completed(roadmap: Roadmap, resource_name: str) -> Roadmap:
    """Return a new Roadmap with the named resource marked as completed.

    Preserves each resource's ``id`` so repository-level indexes built
    from the original roadmap remain valid against the returned copy.
    """
    new_phases: list[RoadmapPhase] = []
    for phase in roadmap.phases:
        new_resources: list[LearningResource] = []
        for r in phase.resources:
            new_r = LearningResource(
                name=r.name,
                skill=r.skill,
                resource_type=r.resource_type,
                estimated_hours=r.estimated_hours,
                url=r.url,
                completed=r.completed or (r.name == resource_name),
                id=r.id,
            )
            new_resources.append(new_r)
        new_phases.append(RoadmapPhase(label=phase.label, resources=new_resources))
    return Roadmap(phases=new_phases)


def mark_completed_by_id(roadmap: Roadmap, resource_id: str) -> Roadmap:
    """Return a new Roadmap with the resource identified by ``resource_id`` completed.

    The API layer uses this for ``PATCH /roadmaps/{id}/resources/{rid}``
    where resources are addressed by their stable uuid id rather than
    human-readable name (multiple resources can share a name).

    Raises:
        KeyError: if no resource in ``roadmap`` has the given id.
    """
    found = False
    new_phases: list[RoadmapPhase] = []
    for phase in roadmap.phases:
        new_resources: list[LearningResource] = []
        for r in phase.resources:
            if r.id == resource_id:
                found = True
                new_resources.append(LearningResource(
                    name=r.name,
                    skill=r.skill,
                    resource_type=r.resource_type,
                    estimated_hours=r.estimated_hours,
                    url=r.url,
                    completed=True,
                    id=r.id,
                ))
            else:
                new_resources.append(LearningResource(
                    name=r.name,
                    skill=r.skill,
                    resource_type=r.resource_type,
                    estimated_hours=r.estimated_hours,
                    url=r.url,
                    completed=r.completed,
                    id=r.id,
                ))
        new_phases.append(RoadmapPhase(label=phase.label, resources=new_resources))
    if not found:
        raise KeyError(f"No resource with id {resource_id!r} in roadmap")
    return Roadmap(phases=new_phases)


def recalculate_match(
    profile: UserProfile,
    job: JobPosting,
    roadmap: Roadmap,
) -> int:
    """Recalculate match % accounting for completed resources.

    Completed resources count their skill as "acquired" for matching purposes.
    """
    # Start with the user's existing skills
    acquired_lower = {s.lower() for s in profile.skills}

    # Add skills from completed resources
    for phase in roadmap.phases:
        for r in phase.resources:
            if r.completed:
                acquired_lower.add(r.skill.lower())

    if len(job.required_skills) == 0:
        return 100

    matched = sum(1 for s in job.required_skills if s.lower() in acquired_lower)
    return round(matched / len(job.required_skills) * 100)
