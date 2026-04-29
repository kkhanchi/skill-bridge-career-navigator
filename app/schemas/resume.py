"""Pydantic v2 schemas for the resume parse endpoint.

The endpoint is a pure function: ``text in -> list of skills out``,
no persistence, no side effects.

Requirement reference: R2.1, R2.2.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import STRICT_MODEL_CONFIG


class ResumeParseRequest(BaseModel):
    """Request body for ``POST /api/v1/resume/parse``.

    ``max_length=50_000`` is a resource-exhaustion guard (R2.2 ceiling).
    Typical resume text is far below this; pathological inputs that hit
    the cap fail validation rather than consuming CPU in the regex
    scan.
    """

    model_config = STRICT_MODEL_CONFIG

    text: str = Field(min_length=1, max_length=50_000)


class ResumeParseResponse(BaseModel):
    """Response body: the list of taxonomy skills detected in ``text``."""

    model_config = STRICT_MODEL_CONFIG

    skills: list[str]
