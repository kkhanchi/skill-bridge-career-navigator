"""Roadmap endpoints under ``/api/v1/roadmaps``.

Two handlers:
  - ``POST /``                                  create from an analysis_id
  - ``PATCH /{id}/resources/{resource_id}``    flip completed flag

Create flow (R5.1 / R5.2 / R6.5):
  1. Look up the analysis via ``analysis_repo.get_for_user`` —
     ownership filter folds cross-tenant access into
     ANALYSIS_NOT_FOUND (R6.5, ADR-015).
  2. Call ``generate_roadmap(analysis.gap, ext.resources)`` —
     every emitted resource already carries a fresh uuid id.
  3. Build the ``resource_index`` mapping uuid -> (phase_idx, resource_idx).
  4. Persist via ``roadmap_repo.create_for_user``. Roadmaps have no
     ``user_id`` column of their own; ownership flows through the
     parent analysis (see :mod:`app.repositories.sql_roadmap_repo`).

Update flow (R5.3 / R5.4 / R5.5 / R6.3):
  1. Call ``ext.roadmap_repo.update_resource_for_user(...)``.
  2. If it returns ``None``, call ``get_for_user`` to decide between
     ROADMAP_NOT_FOUND (roadmap missing or owned by someone else)
     and RESOURCE_NOT_FOUND (roadmap visible but the resource id
     isn't in any phase).

Phase 3 (R6.1, R6.3, R6.5): every handler requires a valid access
token via ``@require_auth``; reads and writes are scoped to
``current_user``.

Design reference: `.kiro/specs/phase-1-rest-api/design.md` §roadmaps handlers.
Requirement reference: R5.1–R5.5, R6.1, R6.3, R6.5, R9.1, R13.7.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from flask import Blueprint, jsonify

from app.auth.decorator import require_auth
from app.core.roadmap_generator import generate_roadmap
from app.extensions import get_ext
from app.repositories.base import RoadmapRecord, UserRecord
from app.schemas.roadmap import (
    LearningResourceDTO,
    ResourceUpdate,
    RoadmapCreate,
    RoadmapPhaseDTO,
    RoadmapResponse,
)
from app.utils.errors import (
    ANALYSIS_NOT_FOUND,
    RESOURCE_NOT_FOUND,
    ROADMAP_NOT_FOUND,
    ApiError,
)
from app.utils.validation import validate_body


bp = Blueprint("roadmaps", __name__)


def _serialize(record: RoadmapRecord) -> dict:
    return RoadmapResponse(
        id=record.id,
        analysis_id=record.analysis_id,
        phases=[
            RoadmapPhaseDTO(
                label=phase.label,
                resources=[
                    LearningResourceDTO(
                        id=res.id,
                        name=res.name,
                        skill=res.skill,
                        resource_type=res.resource_type,
                        estimated_hours=res.estimated_hours,
                        url=res.url,
                        completed=res.completed,
                    )
                    for res in phase.resources
                ],
            )
            for phase in record.roadmap.phases
        ],
        created_at=record.created_at,
        updated_at=record.updated_at,
    ).model_dump(mode="json")


def _build_resource_index(record_phases) -> dict[str, tuple[int, int]]:
    index: dict[str, tuple[int, int]] = {}
    for phase_idx, phase in enumerate(record_phases):
        for resource_idx, resource in enumerate(phase.resources):
            if resource.id:
                index[resource.id] = (phase_idx, resource_idx)
    return index


@bp.post("")
@require_auth
@validate_body(RoadmapCreate)
def create_roadmap_handler(*, body: RoadmapCreate, current_user: UserRecord):
    ext = get_ext()

    analysis_record = ext.analysis_repo.get_for_user(
        body.analysis_id, current_user.id
    )
    if analysis_record is None:
        raise ApiError(ANALYSIS_NOT_FOUND, "Analysis not found", status=404)

    roadmap = generate_roadmap(analysis_record.gap, ext.resources)
    resource_index = _build_resource_index(roadmap.phases)

    now = datetime.now(timezone.utc)
    record = RoadmapRecord(
        id=uuid4().hex,
        analysis_id=body.analysis_id,
        roadmap=roadmap,
        resource_index=resource_index,
        created_at=now,
        updated_at=now,
    )
    stored = ext.roadmap_repo.create_for_user(current_user.id, record)
    return jsonify(_serialize(stored)), 201


@bp.patch("/<roadmap_id>/resources/<resource_id>")
@require_auth
@validate_body(ResourceUpdate)
def patch_resource_handler(
    roadmap_id: str,
    resource_id: str,
    *,
    body: ResourceUpdate,
    current_user: UserRecord,
):
    repo = get_ext().roadmap_repo
    updated = repo.update_resource_for_user(
        roadmap_id, resource_id, current_user.id, body.completed
    )
    if updated is not None:
        return jsonify(_serialize(updated)), 200

    # update_resource_for_user returns None for three reasons — the
    # roadmap is missing OR it's owned by someone else OR the
    # resource id isn't in the roadmap. From the caller's point of
    # view, "owned by someone else" collapses into ROADMAP_NOT_FOUND
    # (ADR-015); we only distinguish the visible-roadmap +
    # missing-resource case.
    existing = repo.get_for_user(roadmap_id, current_user.id)
    if existing is None:
        raise ApiError(ROADMAP_NOT_FOUND, "Roadmap not found", status=404)
    raise ApiError(RESOURCE_NOT_FOUND, "Resource not found in roadmap", status=404)
