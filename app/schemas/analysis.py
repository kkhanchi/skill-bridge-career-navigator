"""Pydantic v2 schemas for the Analysis resource.

An analysis pairs a profile + job with the computed gap result and the
categorizer's output (groups + summary + fallback flag). It's
write-once from the client's perspective (no PATCH / DELETE).

Requirement reference: R4.1.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import STRICT_MODEL_CONFIG


class AnalysisCreate(BaseModel):
    """Payload for ``POST /api/v1/analyses``."""

    model_config = STRICT_MODEL_CONFIG

    profile_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)


class GapResultDTO(BaseModel):
    """Serialized ``core.models.GapResult``."""

    model_config = STRICT_MODEL_CONFIG

    matched_required: list[str]
    missing_required: list[str]
    matched_preferred: list[str]
    missing_preferred: list[str]
    match_percentage: int = Field(ge=0, le=100)


class CategorizationDTO(BaseModel):
    """Serialized ``core.models.CategorizationResult``."""

    model_config = STRICT_MODEL_CONFIG

    groups: dict[str, list[str]]
    summary: str
    is_fallback: bool


class AnalysisResponse(BaseModel):
    """Serialized :class:`AnalysisRecord` returned by analysis endpoints."""

    model_config = STRICT_MODEL_CONFIG

    id: str
    profile_id: str
    job_id: str
    gap: GapResultDTO
    categorization: CategorizationDTO
    created_at: datetime
