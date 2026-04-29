"""Job catalog endpoints under ``/api/v1/jobs``.

Two handlers: ``GET /`` (paginated + filterable) and ``GET /{id}``
(slug lookup). Filtering delegates to the core ``search_jobs`` logic
via :class:`InMemoryJobRepository.list`, keeping the filter semantics
shared between the API and the Streamlit UI.

Design reference: `.kiro/specs/phase-1-rest-api/design.md` §job handlers.
Requirement reference: R3.1–R3.6, R9.1.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from app.extensions import get_ext
from app.repositories.base import JobRecord
from app.repositories.job_repo import InMemoryJobRepository
from app.schemas.common import PageMeta
from app.schemas.job import JobListQuery, JobListResponse, JobResponse
from app.utils.errors import JOB_NOT_FOUND, ApiError
from app.utils.validation import validate_query


bp = Blueprint("jobs", __name__)


def _serialize(record: JobRecord) -> JobResponse:
    """Build a :class:`JobResponse` from a stored :class:`JobRecord`."""
    return JobResponse(
        id=record.id,
        title=record.job.title,
        description=record.job.description,
        required_skills=list(record.job.required_skills),
        preferred_skills=list(record.job.preferred_skills),
        experience_level=record.job.experience_level,
    )


@bp.get("")
@validate_query(JobListQuery)
def list_jobs_handler(*, query: JobListQuery):
    """``GET /api/v1/jobs`` — paginated, filterable list.

    Returns 200 with an envelope of ``items`` + ``meta``. An out-of-range
    page (e.g. page 99 for a 25-job catalog) returns an empty ``items``
    list with the correct ``meta.total`` and ``meta.pages``.
    """
    repo = get_ext().job_repo
    records, total = repo.list(
        page=query.page,
        limit=query.limit,
        keyword=query.keyword,
        skill=query.skill,
    )
    pages = InMemoryJobRepository.page_count(total, query.limit)
    response = JobListResponse(
        items=[_serialize(r) for r in records],
        meta=PageMeta(
            page=query.page,
            limit=query.limit,
            total=total,
            pages=pages,
        ),
    )
    return jsonify(response.model_dump(mode="json")), 200


@bp.get("/<job_id>")
def get_job_handler(job_id: str):
    """``GET /api/v1/jobs/{id}`` — 200 on slug hit, 404 JOB_NOT_FOUND otherwise."""
    record = get_ext().job_repo.get(job_id)
    if record is None:
        raise ApiError(JOB_NOT_FOUND, "Job not found", status=404)
    return jsonify(_serialize(record).model_dump(mode="json")), 200
