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
from flask_cors import CORS

from app.config import CONFIG_MAP
from app.extensions import init_extensions
from app.utils.errors import register_error_handlers
from app.utils.logging import configure_logging

logger = logging.getLogger(__name__)


def _init_cors(app: Flask) -> None:
    """Configure flask-cors from the ``CORS_ORIGINS`` env/config value.

    Policy:
      - Empty ``CORS_ORIGINS``: skip CORS entirely. Prod default; safer
        than a permissive fallback.
      - ``"*"``: allow any origin. Dev default only — explicitly
        documented as unsuitable for prod (ADR-017).
      - Comma-separated list: exact-match allowlist.

    In all cases:
      - ``supports_credentials=False`` — we use Bearer tokens in the
        Authorization header, not cookies, so no credential cookies
        need to travel cross-origin.
      - ``allow_headers`` includes Authorization, Content-Type, and
        X-Correlation-ID so the browser preflight pass ``OPTIONS``
        doesn't strip our auth header.
      - ``expose_headers`` surfaces X-Correlation-ID back to browser
        JS so clients can correlate their request with server logs.
      - ``max_age=600`` caches the preflight response for 10 minutes.

    Design reference: `.kiro/specs/phase-3-auth/design.md` §CORS.
    """
    origins_raw = str(app.config.get("CORS_ORIGINS", "") or "").strip()
    if not origins_raw:
        # Prod default — no CORS headers emitted. Same-origin callers
        # still work; browser JS from other origins is rejected by
        # the browser, not by us.
        return

    if origins_raw == "*":
        origins: str | list[str] = "*"
    else:
        origins = [o.strip() for o in origins_raw.split(",") if o.strip()]

    CORS(
        app,
        resources={r"/api/*": {"origins": origins}},
        supports_credentials=False,
        allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
        expose_headers=["X-Correlation-ID"],
        max_age=600,
    )


def _register_request_hooks(app: Flask) -> None:
    """Install before/after_request hooks.

    Phase 1 hooks (correlation id + access logs):
      - Every request binds ``g.correlation_id`` from the inbound
        ``X-Correlation-ID`` header, falling back to a fresh uuid4 hex.
      - Every response echoes the id back in ``X-Correlation-ID`` (R7.3).
      - Two log lines per request: ``request.start`` (method, path) and
        ``request.end`` (status, duration_ms). Request bodies are never
        logged (R7.6).

    Phase 2 hooks (request-scoped SQL session):
      - When a SQL engine is bound, ``before_request`` opens a
        :class:`Session` and stashes it on ``g.db_session``.
      - ``teardown_request`` commits on success, rolls back on
        exception, always closes.
      - On the memory backend these hooks are no-ops (no engine on the
        Extensions bundle). R4.4.
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

    @app.before_request
    def _db_session_start() -> None:
        # Only open a session when a SQL backend is bound. The memory
        # backend path leaves g.db_session unset; any repo that
        # mistakenly reaches for `get_db_session()` then hits a clear
        # RuntimeError rather than silently operating on a stale
        # module-level factory.
        ext = app.extensions.get("skillbridge")
        if ext is None or ext.session_factory is None:
            return
        g.db_session = ext.session_factory()

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

    @app.teardown_request
    def _db_session_end(exception: BaseException | None) -> None:
        # Pop unconditionally so a session that got opened always gets
        # closed — even if commit or rollback itself raises.
        session = g.pop("db_session", None)
        if session is None:
            return
        try:
            if exception is None:
                session.commit()
            else:
                session.rollback()
        except Exception:
            # Log but don't re-raise — Flask is already unwinding from
            # the original exception (or returning a response) and
            # swallowing here gives the user the original error
            # surface, not a secondary DB failure message.
            # Do NOT include connection-string values in this log (R10.1).
            logger.exception("db_session.teardown_failed")
            try:
                session.rollback()
            except Exception:
                pass
        finally:
            session.close()


def _register_blueprints(app: Flask) -> None:
    """Mount all HTTP blueprints.

    Resource blueprints land under ``/api/v1/<resource>`` (R9.1).
    ``/health`` is served at the unversioned path (R8.3, R9.2).
    Phase 3 adds ``/api/v1/auth`` for registration / login / refresh /
    logout / me.
    """
    from app.api.v1.analyses import bp as analyses_bp
    from app.api.v1.auth import bp as auth_bp
    from app.api.v1.health import bp as health_bp
    from app.api.v1.jobs import bp as jobs_bp
    from app.api.v1.profiles import bp as profiles_bp
    from app.api.v1.resume import bp as resume_bp
    from app.api.v1.roadmaps import bp as roadmaps_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp, url_prefix="/api/v1/auth")
    app.register_blueprint(profiles_bp, url_prefix="/api/v1/profiles")
    app.register_blueprint(resume_bp, url_prefix="/api/v1/resume")
    app.register_blueprint(jobs_bp, url_prefix="/api/v1/jobs")
    app.register_blueprint(analyses_bp, url_prefix="/api/v1/analyses")
    app.register_blueprint(roadmaps_bp, url_prefix="/api/v1/roadmaps")


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
    _init_cors(app)
    init_extensions(app)
    register_error_handlers(app)
    _register_request_hooks(app)
    _register_blueprints(app)

    return app
