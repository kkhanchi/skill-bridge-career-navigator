"""Pydantic v2 schemas for the Roadmap resource.

Requirement reference: R5.1, R5.3.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import STRICT_MODEL_CONFIG


class RoadmapCreate(BaseModel):
    """Payload for ``POST /api/v1/roadmaps``.

    A roadmap is derived from an existing analysis: the ``analysis_id``
    points at a stored ``AnalysisRecord`` whose gap drives
    ``generate_roadmap``.
    """

    model_config = STRICT_MODEL_CONFIG

    analysis_id: str = Field(min_length=1)


class LearningResourceDTO(BaseModel):
    """Serialized :class:`core.models.LearningResource` with its id."""

    model_config = STRICT_MODEL_CONFIG

    id: str
    name: str
    skill: str
    resource_type: str
    estimated_hours: int
    url: str
    completed: bool


class RoadmapPhaseDTO(BaseModel):
    """Serialized :class:`core.models.RoadmapPhase`."""

    model_config = STRICT_MODEL_CONFIG

    label: str
    resources: list[LearningResourceDTO]


class RoadmapResponse(BaseModel):
    """Serialized :class:`RoadmapRecord`."""

    model_config = STRICT_MODEL_CONFIG

    id: str
    analysis_id: str
    phases: list[RoadmapPhaseDTO]
    created_at: datetime
    updated_at: datetime


class ResourceUpdate(BaseModel):
    """Payload for ``PATCH /roadmaps/{id}/resources/{resource_id}``."""

    model_config = STRICT_MODEL_CONFIG

    completed: bool
