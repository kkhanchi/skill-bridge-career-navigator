"""Profile CRUD endpoints under ``/api/v1/profiles``.

Four handlers — create/read/update/delete — all wired through the
``ProfileRepository`` Protocol. Validation is two-layered:

  * Pydantic schema (`ProfileCreate` / `ProfileUpdate`) catches
    malformed payloads and emits ``VALIDATION_FAILED`` (400).
  * The core :mod:`core.profile_manager` raises ``ValueError`` for
    domain violations (dedup drops everything, skill too long, etc.),
    which the handler converts to ``PROFILE_INVALID`` (400).

Design reference: `.kiro/specs/phase-1-rest-api/design.md` §Profile handlers.
Requirement reference: R1.1–R1.7, R9.1.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from app.core.profile_manager import create_profile as core_create_profile
from app.core.profile_manager import update_profile as core_update_profile
from app.core.models import UserProfile
from app.extensions import get_ext
from app.repositories.base import ProfileRecord
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
@validate_body(ProfileCreate)
def create_profile_handler(*, body: ProfileCreate):
    """``POST /api/v1/profiles`` — create a profile, return 201.

    Domain validation (dedup / size / length) runs in the core module.
    Domain errors surface as ``PROFILE_INVALID`` (400).
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

    record = get_ext().profile_repo.create(profile)
    return jsonify(_serialize(record)), 201


@bp.get("/<profile_id>")
def get_profile_handler(profile_id: str):
    """``GET /api/v1/profiles/{id}`` — 200 or 404 ``NOT_FOUND``."""
    record = get_ext().profile_repo.get(profile_id)
    if record is None:
        raise ApiError(NOT_FOUND, "Profile not found", status=404)
    return jsonify(_serialize(record)), 200


@bp.patch("/<profile_id>")
@validate_body(ProfileUpdate)
def patch_profile_handler(profile_id: str, *, body: ProfileUpdate):
    """``PATCH /api/v1/profiles/{id}`` — apply partial updates, return 200.

    Order of operations inside the handler:
      1. Fetch existing record (404 ``NOT_FOUND`` if missing).
      2. Run skill add/remove through ``core.update_profile`` (may raise
         ``ValueError`` → ``PROFILE_INVALID``).
      3. Apply direct field overrides (name / years / education / role).
      4. Persist via ``ProfileRepository.update`` — stamps ``updated_at``.
    """
    repo = get_ext().profile_repo
    existing = repo.get(profile_id)
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

    updated = repo.update(profile_id, working)
    # Defensive: update should not return None here because we already
    # confirmed existence above, but honour the Protocol contract.
    if updated is None:
        raise ApiError(NOT_FOUND, "Profile not found", status=404)
    return jsonify(_serialize(updated)), 200


@bp.delete("/<profile_id>")
def delete_profile_handler(profile_id: str):
    """``DELETE /api/v1/profiles/{id}`` — 204 on success, 404 if missing.

    No cascade: analyses/roadmaps that referenced the deleted profile
    become orphaned records accessible only by their own ids (documented
    Phase 1 limitation).
    """
    deleted = get_ext().profile_repo.delete(profile_id)
    if not deleted:
        raise ApiError(NOT_FOUND, "Profile not found", status=404)
    return "", 204
