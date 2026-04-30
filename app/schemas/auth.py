"""Pydantic v2 schemas for the /auth/* endpoints (Phase 3).

Request schemas mirror the design spec exactly:

  - RegisterRequest / LoginRequest: {email, password}. Password is
    8..128 chars, non-whitespace-only. Rejection surfaces as
    VALIDATION_FAILED.
  - RefreshRequest / LogoutRequest: {refresh} — the refresh JWT string.
    Only presence is enforced here; signature/type validation happens
    downstream in tokens.decode_token.

Response schemas:

  - UserResponse: public projection of :class:`UserRecord` (id, email,
    created_at — never password_hash).
  - TokenPairResponse: returned from /register and /login (includes
    the user object + both tokens).
  - RefreshPairResponse: returned from /refresh (no user object — the
    caller already knows who they are since they hold the refresh).

All models use ``STRICT_MODEL_CONFIG`` so unknown fields are rejected
with VALIDATION_FAILED (consistent with Phase 1 schema behaviour).

Design reference: `.kiro/specs/phase-3-auth/design.md` §Endpoints.
Requirement reference: R1.1, R1.2, R2.1, R2.2, R3.1, R3.2, R4.1, R4.2, R5.1.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.schemas.common import STRICT_MODEL_CONFIG


class RegisterRequest(BaseModel):
    """Payload for POST /api/v1/auth/register."""

    model_config = STRICT_MODEL_CONFIG

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def _password_not_all_whitespace(self) -> "RegisterRequest":
        # 8..128 chars of whitespace would technically pass the length
        # check but isn't a meaningful password. Mirrors the design's
        # "not all-whitespace" rule (R1.2).
        if self.password.strip() == "":
            raise ValueError("Password must not be all whitespace")
        return self


class LoginRequest(BaseModel):
    """Payload for POST /api/v1/auth/login.

    Identical shape to RegisterRequest; keeping them as distinct types
    rather than an alias lets the handler signatures self-document
    which verb they serve.
    """

    model_config = STRICT_MODEL_CONFIG

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def _password_not_all_whitespace(self) -> "LoginRequest":
        if self.password.strip() == "":
            raise ValueError("Password must not be all whitespace")
        return self


class RefreshRequest(BaseModel):
    """Payload for POST /api/v1/auth/refresh."""

    model_config = STRICT_MODEL_CONFIG

    # Only presence enforced at the schema layer — the token itself
    # is verified by tokens.decode_token(expected_type="refresh"),
    # which owns the real failure codes (TOKEN_EXPIRED, TOKEN_INVALID).
    refresh: str = Field(min_length=1)


class LogoutRequest(BaseModel):
    """Payload for POST /api/v1/auth/logout."""

    model_config = STRICT_MODEL_CONFIG

    refresh: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class UserResponse(BaseModel):
    """Public projection of UserRecord. Never includes password_hash."""

    model_config = STRICT_MODEL_CONFIG

    id: str
    email: str
    created_at: datetime


class TokenPairResponse(BaseModel):
    """/register + /login response body: user + both tokens."""

    model_config = STRICT_MODEL_CONFIG

    user: UserResponse
    access: str
    refresh: str


class RefreshPairResponse(BaseModel):
    """/refresh response body: new tokens only, no user object."""

    model_config = STRICT_MODEL_CONFIG

    access: str
    refresh: str


class MeResponse(BaseModel):
    """/me response body: just the current user."""

    model_config = STRICT_MODEL_CONFIG

    user: UserResponse
