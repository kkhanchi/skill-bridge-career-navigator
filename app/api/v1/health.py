"""Liveness probe endpoint.

``GET /health`` returns ``200 {"status": "ok"}`` unconditionally — no
repository reads, no Groq calls (R8.1, R8.2). Served at the unversioned
path ``/health``, outside ``/api/v1/`` (R8.3, R9.2).

Design reference: `.kiro/specs/phase-1-rest-api/design.md` §GET /health.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

# Blueprint name kept short; the route itself is absolute (``/health``).
bp = Blueprint("health", __name__)


@bp.get("/health")
def health():
    """Return a static liveness payload."""
    return jsonify({"status": "ok"}), 200
