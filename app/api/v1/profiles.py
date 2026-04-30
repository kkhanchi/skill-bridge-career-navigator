"""Profile CRUD endpoints under ``/api/v1/profiles``.

Four handlers — create/read/update/delete — all wired through the
``ProfileRepository`` Protocol. Validation is two-layered:

  * Pydantic schema (`ProfileCreate` / `ProfileUpdate`) catches
    malformed payloads and emits ``VALIDATION_FAILED`` (400).
  * The core :mod:`core.profile_manager` raises ``ValueError`` for
    domain violations (dedup drops everything, skill too long, etc.),
    which the handler converts to ``PROFILE_INVALID`` (400).

Phase 3 (R6.1): every handler requires a valid access token via
``@require_auth`` and scopes repository calls to ``current_user.id``
through the ``*_for_user`` methods. Cross-tenant access collapses to
``404 NOT_FOUND`` — wrong-owner is indistinguishable from
doesn't-exist (ADR-015 anti-enumeration).

Design reference: `.kiro/specs/phase-1-rest-api/design.md` §Profile handlers.
Requirement reference: R1.1–R1.7, R6.1, R9.1, R13.7, R13.8.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from app.auth.decorator import require_auth
from app.core.profile_manager import create_profile as core_create_profile
from app.core.profile_manager import update_profile as core_update_profile
from app.core.models import UserProfile
from app.extensions import get_ext
from app.repositories.base import ProfileRecord, UserRecord
from app.schemas.profile import ProfileCreate, ProfileResponse, ProfileUpdate
from app.utils.errors import (
    NOT_FOUND,
    PROFILE_INVALID,
    ApiError,
)
from app.utils.validation import validate_body


bp = Blueprint("profiles", __name__)


# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------


def _serialize(record: ProfileRecord) -> dict:
    """Convert a :class:`ProfileRecord` to a JSON-ready dict via Pydantic."""
    return ProfileResponse(
        id=record.id,
        name=record.profile.name,
        skills=list(record.profile.skills),
        experience_years=record.profile.experience_years,
        education=record.profile.education,
        target_role=record.profile.target_role,
        created_at=record.created_at,
        updated_at=record.updated_at,
    ).model_dump(mode="json")


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


@bp.post("")
@require_auth
@validate_body(ProfileCreate)
def create_profile_handler(
    *, body: ProfileCreate, current_user: UserRecord
):
    """``POST /api/v1/profiles`` — create a profile, return 201.

    Stamped with ``current_user.id`` so only the creator can read or
    mutate the profile afterwards.
    """
    try:
        profile, _notification = core_create_profile(
            name=body.name,
            skills=list(body.skills),
            experience_years=body.experience_years,
            education=body.education,
            target_role=body.target_role,
        )
    except ValueError as err:
        raise ApiError(PROFILE_INVALID, str(err), status=400) from err

    record = get_ext().profile_repo.create_for_user(current_user.id, profile)
    return jsonify(_serialize(record)), 201


@bp.get("/<profile_id>")
@require_auth
def get_profile_handler(profile_id: str, *, current_user: UserRecord):
    """``GET /api/v1/profiles/{id}`` — 200 or 404 ``NOT_FOUND``.

    Anti-enumeration: 404 for both "unknown id" and "id owned by a
    different user".
    """
    record = get_ext().profile_repo.get_for_user(profile_id, current_user.id)
    if record is None:
        raise ApiError(NOT_FOUND, "Profile not found", status=404)
    return jsonify(_serialize(record)), 200


@bp.patch("/<profile_id>")
@require_auth
@validate_body(ProfileUpdate)
def patch_profile_handler(
    profile_id: str, *, body: ProfileUpdate, current_user: UserRecord
):
    """``PATCH /api/v1/profiles/{id}`` — apply partial updates, return 200."""
    repo = get_ext().profile_repo
    existing = repo.get_for_user(profile_id, current_user.id)
    if existing is None:
        raise ApiError(NOT_FOUND, "Profile not found", status=404)

    # Step 1: skill add/remove (idempotent, goes through core validation).
    try:
        working = core_update_profile(
            existing.profile,
            added_skills=body.added_skills,
            removed_skills=body.removed_skills,
        )
    except ValueError as err:
        raise ApiError(PROFILE_INVALID, str(err), status=400) from err

    # Step 2: direct field overrides (None means "leave unchanged").
    working = UserProfile(
        name=body.name if body.name is not None else working.name,
        skills=working.skills,
        experience_years=(
            body.experience_years
            if body.experience_years is not None
            else working.experience_years
        ),
        education=(
            body.education if body.education is not None else working.education
        ),
        target_role=(
            body.target_role if body.target_role is not None else working.target_role
        ),
    )

    updated = repo.update_for_user(profile_id, current_user.id, working)
    # Defensive: update should not return None here because we already
    # confirmed existence above, but honour the Protocol contract.
    if updated is None:
        raise ApiError(NOT_FOUND, "Profile not found", status=404)
    return jsonify(_serialize(updated)), 200


@bp.delete("/<profile_id>")
@require_auth
def delete_profile_handler(profile_id: str, *, current_user: UserRecord):
    """``DELETE /api/v1/profiles/{id}`` — 204 on success, 404 if missing.

    Phase 3: no cascade at this layer — analyses/roadmaps owned by the
    same user remain accessible by their ids until deleted directly
    (documented Phase 1 limitation, unchanged).
    """
    deleted = get_ext().profile_repo.delete_for_user(profile_id, current_user.id)
    if not deleted:
        raise ApiError(NOT_FOUND, "Profile not found", status=404)
    return "", 204
