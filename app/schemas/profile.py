"""Pydantic v2 schemas for the Profile resource.

Three boundary schemas:
  - :class:`ProfileCreate`   — POST /api/v1/profiles body
  - :class:`ProfileUpdate`   — PATCH /api/v1/profiles/{id} body
  - :class:`ProfileResponse` — response body (GET/POST/PATCH)

Field-level limits (length/range) live at the schema boundary; the
:mod:`core.profile_manager` module enforces domain-level semantics
(deduplication, per-skill length, list size). Schema errors produce
``VALIDATION_FAILED`` (R1.2); domain errors become ``PROFILE_INVALID``
(R1.3). This two-layer validation is intentional — the schema rejects
obviously-malformed payloads before they reach business logic.

Requirement reference: R1.1, R1.6.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import STRICT_MODEL_CONFIG


class ProfileCreate(BaseModel):
    """Payload for ``POST /api/v1/profiles``.

    Skill-list size (1..30) and per-skill length (<=100) are enforced
    here so the error surfaces as ``VALIDATION_FAILED`` rather than
    ``PROFILE_INVALID``. Duplicate skills pass the schema — the domain
    layer deduplicates and emits an advisory notification.
    """

    model_config = STRICT_MODEL_CONFIG

    name: str = Field(min_length=1, max_length=200)
    skills: list[str] = Field(min_length=1, max_length=30)
    experience_years: int = Field(ge=0, le=80)
    education: str = Field(max_length=200, default="")
    target_role: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _each_skill_has_content(self) -> "ProfileCreate":
        for skill in self.skills:
            stripped = skill.strip()
            if not stripped:
                raise ValueError("Each skill must be a non-empty string")
            if len(stripped) > 100:
                raise ValueError("Skill name must be 100 characters or fewer")
        return self


class ProfileUpdate(BaseModel):
    """Payload for ``PATCH /api/v1/profiles/{id}``.

    All fields optional; the model validator requires at least one of
    them to be present so a PATCH without changes is rejected early
    with ``VALIDATION_FAILED`` rather than a silent 200.
    """

    model_config = STRICT_MODEL_CONFIG

    added_skills: list[str] | None = None
    removed_skills: list[str] | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    experience_years: int | None = Field(default=None, ge=0, le=80)
    education: str | None = Field(default=None, max_length=200)
    target_role: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def _requires_at_least_one_field(self) -> "ProfileUpdate":
        if all(
            value is None
            for value in (
                self.added_skills,
                self.removed_skills,
                self.name,
                self.experience_years,
                self.education,
                self.target_role,
            )
        ):
            raise ValueError("PATCH body must contain at least one field to update")
        return self


class ProfileResponse(BaseModel):
    """Serialized ``ProfileRecord`` returned by every profile endpoint."""

    model_config = STRICT_MODEL_CONFIG

    id: str
    name: str
    skills: list[str]
    experience_years: int
    education: str
    target_role: str
    created_at: datetime
    updated_at: datetime
