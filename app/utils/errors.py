"""Uniform error contract for the SkillBridge API.

Every 4xx / 5xx response carries the Error_Envelope body::

    {"error": {"code": <string>, "message": <string>, "details"?: <object>}}

A single :class:`ApiError` exception type plus three registered handlers
produce this shape for every failure mode: raised ``ApiError``,
``werkzeug`` HTTPExceptions (unknown route, disallowed method, bad JSON,
...), and any uncaught ``Exception``.

Design reference: `.kiro/specs/phase-1-rest-api/design.md` §Error Contract.
Requirement reference: R6.1, R6.2, R6.4, R6.5.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Flask, g, has_request_context, jsonify
from werkzeug.exceptions import HTTPException

logger = logging.getLogger(__name__)


# ---- Closed set of error codes (R6.2) --------------------------------------
VALIDATION_FAILED = "VALIDATION_FAILED"
PROFILE_INVALID = "PROFILE_INVALID"
NOT_FOUND = "NOT_FOUND"
PROFILE_NOT_FOUND = "PROFILE_NOT_FOUND"
JOB_NOT_FOUND = "JOB_NOT_FOUND"
ANALYSIS_NOT_FOUND = "ANALYSIS_NOT_FOUND"
ROADMAP_NOT_FOUND = "ROADMAP_NOT_FOUND"
RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
INTERNAL_ERROR = "INTERNAL_ERROR"

# Mapping Flask HTTPException status codes to our own codes when the
# framework raises them directly (e.g. unknown route -> 404).
_HTTP_STATUS_TO_CODE: dict[int, str] = {
    400: VALIDATION_FAILED,
    404: NOT_FOUND,
    405: "METHOD_NOT_ALLOWED",
    415: "UNSUPPORTED_MEDIA_TYPE",
}


class ApiError(Exception):
    """An error intended to reach the client as an Error_Envelope response.

    Handlers raise this exception directly; the registered handler turns
    it into a JSON response with the Error_Envelope shape. ``details`` is
    optional and omitted from the response body when ``None``.
    """

    def __init__(
        self,
        code: str,
        message: str,
        status: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details


def _envelope(code: str, message: str, details: dict[str, Any] | None = None):
    """Build a JSON response matching the Error_Envelope contract."""
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return jsonify(body)


def _cid() -> str:
    """Best-effort correlation id for logging outside a known context."""
    if has_request_context():
        return getattr(g, "correlation_id", "-")
    return "-"


def register_error_handlers(app: Flask) -> None:
    """Wire the three error handlers the Error_Envelope contract depends on."""

    @app.errorhandler(ApiError)
    def _handle_api_error(err: ApiError):
        # Known, intentional error. Info-level log is enough; the handler
        # is the author of the failure semantics, not a surprise.
        logger.info(
            "api_error",
            extra={"extra_fields": {
                "code": err.code,
                "status": err.status,
                "cid": _cid(),
            }},
        )
        return _envelope(err.code, err.message, err.details), err.status

    @app.errorhandler(HTTPException)
    def _handle_http_exception(err: HTTPException):
        # Flask-raised exceptions: unknown route, disallowed method, etc.
        status = err.code or 500
        code = _HTTP_STATUS_TO_CODE.get(status, f"HTTP_{status}")
        message = err.description or err.name or "HTTP error"
        return _envelope(code, message), status

    @app.errorhandler(Exception)
    def _handle_unexpected(err: Exception):  # pragma: no cover - exercised via test-only route
        # Anything uncaught: log full traceback with cid, then a generic 500.
        logger.exception(
            "unhandled_exception",
            extra={"extra_fields": {"cid": _cid()}},
        )
        return (
            _envelope(INTERNAL_ERROR, "An unexpected error occurred"),
            500,
        )
