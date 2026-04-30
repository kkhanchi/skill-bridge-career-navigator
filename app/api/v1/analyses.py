"""Gap-analysis endpoints under ``/api/v1/analyses``.

Two handlers: ``POST /`` (create) and ``GET /{id}`` (fetch).

Create flow (R4.1 / R4.2 / R4.3):
  1. Validate body via Pydantic (VALIDATION_FAILED on missing ids).
  2. Look up profile via ``profile_repo.get_for_user`` — the
     ownership filter folds the cross-tenant case into a plain
     ``PROFILE_NOT_FOUND`` (R6.4, ADR-015).
  3. Look up job — 404 JOB_NOT_FOUND if missing. Jobs are the
     catalog and are public across tenants (R7.2), so no
     ownership filter.
  4. Compute gap via ``core.gap_analyzer.analyze_gap``.
  5. Categorize gap via the configured ``Categorizer``. Groq failures
     are handled inside ``GroqCategorizer`` and surface as
     ``is_fallback=True``; the API never returns 5xx for Groq issues
     (R4.6).
  6. Persist via ``analysis_repo.create_for_user`` stamped with
     ``current_user.id``.

Phase 3 (R6.1, R6.4): every handler requires a valid access token
via ``@require_auth``; reads and writes are scoped to ``current_user``.

Design reference: `.kiro/specs/phase-1-rest-api/design.md` §analyses handlers.
Requirement reference: R4.1–R4.6, R6.1, R6.4, R9.1, R13.7.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from flask import Blueprint, jsonify

from app.auth.decorator import require_auth
from app.core.gap_analyzer import analyze_gap
from app.extensions import get_ext
from app.repositories.base import AnalysisRecord, UserRecord
from app.schemas.analysis import (
    AnalysisCreate,
    AnalysisResponse,
    CategorizationDTO,
    GapResultDTO,
)
from app.utils.errors import (
    ANALYSIS_NOT_FOUND,
    JOB_NOT_FOUND,
    PROFILE_NOT_FOUND,
    ApiError,
)
from app.utils.validation import validate_body


bp = Blueprint("analyses", __name__)


def _serialize(record: AnalysisRecord) -> dict:
    return AnalysisResponse(
        id=record.id,
        profile_id=record.profile_id,
        job_id=record.job_id,
        gap=GapResultDTO(
            matched_required=list(record.gap.matched_required),
            missing_required=list(record.gap.missing_required),
            matched_preferred=list(record.gap.matched_preferred),
            missing_preferred=list(record.gap.missing_preferred),
            match_percentage=record.gap.match_percentage,
        ),
        categorization=CategorizationDTO(
            groups=dict(record.categorization.groups),
            summary=record.categorization.summary,
            is_fallback=record.categorization.is_fallback,
        ),
        created_at=record.created_at,
    ).model_dump(mode="json")


@bp.post("")
@require_auth
@validate_body(AnalysisCreate)
def create_analysis_handler(*, body: AnalysisCreate, current_user: UserRecord):
    ext = get_ext()

    # Ownership-filtered profile lookup. A profile owned by a different
    # user looks identical to a missing id — 404 PROFILE_NOT_FOUND.
    profile_record = ext.profile_repo.get_for_user(
        body.profile_id, current_user.id
    )
    if profile_record is None:
        raise ApiError(PROFILE_NOT_FOUND, "Profile not found", status=404)

    # Jobs are the shared catalog — no ownership filter.
    job_record = ext.job_repo.get(body.job_id)
    if job_record is None:
        raise ApiError(JOB_NOT_FOUND, "Job not found", status=404)

    gap = analyze_gap(profile_record.profile, job_record.job)

    missing = list(gap.missing_required) + list(gap.missing_preferred)
    matched = list(gap.matched_required) + list(gap.matched_preferred)
    categorization = ext.categorizer.categorize(
        missing_skills=missing,
        matched_skills=matched,
    )

    record = AnalysisRecord(
        id=uuid4().hex,
        profile_id=body.profile_id,
        job_id=body.job_id,
        gap=gap,
        categorization=categorization,
        created_at=datetime.now(timezone.utc),
    )
    stored = ext.analysis_repo.create_for_user(current_user.id, record)
    return jsonify(_serialize(stored)), 201


@bp.get("/<analysis_id>")
@require_auth
def get_analysis_handler(analysis_id: str, *, current_user: UserRecord):
    record = get_ext().analysis_repo.get_for_user(analysis_id, current_user.id)
    if record is None:
        raise ApiError(ANALYSIS_NOT_FOUND, "Analysis not found", status=404)
    return jsonify(_serialize(record)), 200
