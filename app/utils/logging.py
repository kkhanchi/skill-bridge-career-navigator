"""Structured logging with per-request correlation IDs.

Uses stdlib ``logging`` + a custom ``Formatter`` + a ``Filter`` that reads
``g.correlation_id`` during requests. No third-party deps (see ADR-004).

Log records always carry the base fields ``ts``, ``level``, ``logger``,
``cid``, ``msg``. Handlers may attach additional per-event fields by
passing ``extra={"extra_fields": {...}}``.

Design reference: `.kiro/specs/phase-1-rest-api/design.md` §Logging.
Requirement reference: R7.4, R7.6.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from flask import Flask, g, has_request_context


class CorrelationIdFilter(logging.Filter):
    """Inject the request's correlation id onto every log record.

    Outside a request context (e.g. startup logs) the id is ``"-"``.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        if has_request_context():
            record.correlation_id = getattr(g, "correlation_id", "-")
        else:
            record.correlation_id = "-"
        return True


class JsonFormatter(logging.Formatter):
    """Serialise a log record as a single-line JSON object.

    Contract (R7.4): every record has at minimum ``ts``, ``level``,
    ``logger``, ``cid``, ``msg``. Additional fields passed via
    ``extra={"extra_fields": {...}}`` are merged into the top-level
    object.

    Request bodies are never emitted from here — callers are forbidden
    from placing them in ``extra_fields`` (R7.6).
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "cid": getattr(record, "correlation_id", "-"),
            "msg": record.getMessage(),
        }
        extra_fields = getattr(record, "extra_fields", None)
        if isinstance(extra_fields, dict):
            # Never overwrite the fixed base fields from extras.
            for key, value in extra_fields.items():
                if key not in payload:
                    payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class _PlainTextFormatter(logging.Formatter):
    """Fallback formatter used in TestConfig (JSON_LOGS=False).

    Keeps tests readable; still attaches the correlation id in a compact
    prefix so assertions can match against it if needed.
    """

    _FMT = "%(asctime)s %(levelname)s [%(correlation_id)s] %(name)s: %(message)s"

    def __init__(self) -> None:
        super().__init__(fmt=self._FMT, datefmt="%H:%M:%S")


def configure_logging(app: Flask) -> None:
    """Install handlers on the root logger based on Flask config.

    Idempotent: calling twice on the same process doesn't duplicate
    handlers. Per-app isolation is not a goal here (logging is a process
    concern in Flask), but tests that recreate apps won't pile up handlers.
    """

    json_logs: bool = bool(app.config.get("JSON_LOGS", True))
    level_name: str = str(app.config.get("LOG_LEVEL", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    # Remove any handler we previously installed so repeated create_app
    # calls in the test suite stay clean.
    for handler in list(root.handlers):
        if getattr(handler, "_skillbridge_installed", False):
            root.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(JsonFormatter() if json_logs else _PlainTextFormatter())
    handler.addFilter(CorrelationIdFilter())
    handler._skillbridge_installed = True  # type: ignore[attr-defined]
    root.addHandler(handler)

    # Silence Flask's default request logger — we emit our own request.start
    # / request.end lines carrying the correlation id.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
