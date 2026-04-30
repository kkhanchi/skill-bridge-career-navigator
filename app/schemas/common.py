"""Shared Pydantic v2 schemas used across resources.

- :class:`ErrorBody` / :class:`ErrorResponse`: the Error_Envelope shape
  documented in R6.1. Responses serialise via the handler in
  ``app.utils.errors`` rather than through Pydantic, but this model
  exists so tests and (future) OpenAPI generation can reference it.
- :class:`PageMeta`: pagination metadata attached to list responses
  (R3.1).

Design reference: `.kiro/specs/phase-1-rest-api/design.md` §Pydantic schemas.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# Reusable config: reject unknown fields in request payloads (catches
# typos early) and auto-strip whitespace from string fields. Response
# models don't need this but inheriting it is harmless.
STRICT_MODEL_CONFIG = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ErrorBody(BaseModel):
    """Inner object of the Error_Envelope response body."""

    model_config = STRICT_MODEL_CONFIG

    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    """The full Error_Envelope: ``{"error": {...}}``."""

    model_config = STRICT_MODEL_CONFIG

    error: ErrorBody


class PageMeta(BaseModel):
    """Pagination metadata attached to every list endpoint response."""

    model_config = STRICT_MODEL_CONFIG

    page: int = Field(ge=1)
    limit: int = Field(ge=1)
    total: int = Field(ge=0)
    pages: int = Field(ge=0)
