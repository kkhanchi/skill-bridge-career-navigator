"""SkillBridge Flask application package + app factory.

The :func:`create_app` factory builds and returns a fully configured
Flask instance. It is idempotent: each call returns an independent app
with independent extensions (R10.2), which keeps tests isolated.

Design reference: `.kiro/specs/phase-1-rest-api/design.md` §App Factory.
Requirement reference: R7.1, R7.2, R7.3, R7.5, R8.1, R8.3, R9.1, R9.2,
R10.1, R10.2.
"""

from __future__ import annotations

import logging
import time
from uuid import uuid4

from flask import Flask, g, request

from app.config import CONFIG_MAP
from app.extensions import init_extensions
from app.utils.errors import register_error_handlers
from app.utils.logging import configure_logging

logger = logging.getLogger(__name__)


def _register_request_hooks(app: Flask) -> None:
    """Install before/after_request hooks for correlation id + access logs.

    Contract:
      - Every request binds ``g.correlation_id`` from the inbound
        ``X-Correlation-ID`` header, falling back to a fresh uuid4 hex.
      - Every response echoes the id back in ``X-Correlation-ID`` (R7.3).
      - Two log lines per request: ``request.start`` (method, path) and
        ``request.end`` (status, duration_ms). Request bodies are never
        logged (R7.6).
    """

    @app.before_request
    def _cid_start() -> None:
        incoming = request.headers.get("X-Correlation-ID", "").strip()
        g.correlation_id = incoming or uuid4().hex
        g.request_start = time.monotonic()
        logger.info(
            "request.start",
            extra={"extra_fields": {"method": request.method, "path": request.path}},
        )

    @app.after_request
    def _cid_end(response):
        # Always emit the header, even on error responses (R6.6, R7.3).
        response.headers["X-Correlation-ID"] = getattr(g, "correlation_id", "-")
        start = getattr(g, "request_start", None)
        if start is not None:
            duration_ms = int((time.monotonic() - start) * 1000)
        else:
            duration_ms = 0
        logger.info(
            "request.end",
            extra={"extra_fields": {
                "status": response.status_code,
                "duration_ms": duration_ms,
            }},
        )
        return response


def _register_blueprints(app: Flask) -> None:
    """Mount all HTTP blueprints.

    Resource blueprints land under ``/api/v1/<resource>`` (R9.1).
    ``/health`` is served at the unversioned path (R8.3, R9.2).
    Blueprints for profiles/resume/jobs/analyses/roadmaps are added in
    later stages; this function is extended as they arrive.
    """
    from app.api.v1.health import bp as health_bp
    app.register_blueprint(health_bp)


def create_app(config_name: str = "dev") -> Flask:
    """Build a configured Flask app.

    Args:
        config_name: One of ``"dev"``, ``"test"``, ``"prod"``.

    Returns:
        A new Flask instance. Each call produces an independent app
        with independent extension state (R10.2).
    """
    if config_name not in CONFIG_MAP:
        raise ValueError(
            f"Unknown config_name {config_name!r}; "
            f"expected one of {sorted(CONFIG_MAP.keys())}"
        )

    app = Flask(__name__)
    app.config.from_object(CONFIG_MAP[config_name])

    configure_logging(app)
    init_extensions(app)
    register_error_handlers(app)
    _register_request_hooks(app)
    _register_blueprints(app)

    return app
