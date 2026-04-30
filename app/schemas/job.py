"""Pydantic v2 schemas for the Job resource.

Three schemas:
  - :class:`JobListQuery`    — `GET /api/v1/jobs` querystring
  - :class:`JobResponse`     — single-job response body
  - :class:`JobListResponse` — paginated list response body

Requirement reference: R3.1, R3.2, R3.3, R3.4.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import PageMeta, STRICT_MODEL_CONFIG


class JobListQuery(BaseModel):
    """Query parameters for ``GET /api/v1/jobs``.

    Defaults (page=1, limit=20) per R3.2. Upper limit 100 per R3.3.
    Both keyword and skill default to empty string so a bare GET
    returns every job.
    """

    model_config = STRICT_MODEL_CONFIG

    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=100)
    keyword: str = ""
    skill: str = ""


class JobResponse(BaseModel):
    """Serialized :class:`JobRecord` with its stable slug id."""

    model_config = STRICT_MODEL_CONFIG

    id: str
    title: str
    description: str
    required_skills: list[str]
    preferred_skills: list[str]
    experience_level: str


class JobListResponse(BaseModel):
    """Envelope for paginated job responses."""

    model_config = STRICT_MODEL_CONFIG

    items: list[JobResponse]
    meta: PageMeta
