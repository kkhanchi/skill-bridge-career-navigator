"""Resume parse endpoint under ``/api/v1/resume``.

A single ``POST /parse`` handler that forwards to
:func:`core.resume_parser.parse_resume` with the taxonomy loaded once
at startup by :mod:`app.extensions`. Pure read path — no writes.

Design reference: `.kiro/specs/phase-1-rest-api/design.md` §resume endpoints.
Requirement reference: R2.1, R2.2, R2.3, R9.1.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from app.core.resume_parser import parse_resume
from app.extensions import get_ext
from app.schemas.resume import ResumeParseRequest, ResumeParseResponse
from app.utils.validation import validate_body


bp = Blueprint("resume", __name__)


@bp.post("/parse")
@validate_body(ResumeParseRequest)
def parse_resume_handler(*, body: ResumeParseRequest):
    skills = parse_resume(body.text, get_ext().taxonomy)
    return jsonify(ResumeParseResponse(skills=skills).model_dump(mode="json")), 200
