"""Process-wide singletons attached to a Flask app.

Phase 1 shipped a memory-only :class:`Extensions`. Phase 2 extends it
with dual-backend selection: at ``init_extensions`` time we pick
between the in-memory repositories and a SQLAlchemy engine + session
factory + SQL repositories based on config.

Backend precedence (see :func:`pick_backend`):

1. An explicit ``REPO_BACKEND`` wins (useful in tests and benchmarks).
2. An empty ``DATABASE_URL`` means "memory".
3. ``sqlite:`` or ``postgresql:`` URLs pick the corresponding SQL
   dialect.
4. Any other scheme raises :class:`RuntimeError` so a misconfigured
   prod boot fails loudly at startup instead of producing mysterious
   runtime errors.

Design reference: `.kiro/specs/phase-2-persistence/design.md` §Extensions.
Requirement reference: R3.1, R3.2, R3.3, R3.4, R4.6, R10.1, R10.2,
R10.3, R10.4.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from flask import Flask, current_app
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.ai_engine import FallbackCategorizer, SkillCategorizerInterface, get_categorizer
from app.core.job_catalog import load_jobs
from app.core.models import LearningResource
from app.core.resume_parser import load_taxonomy
from app.core.roadmap_generator import _load_resources
from app.db.engine import build_engine
from app.db.session import set_session_factory
from app.repositories.analysis_repo import InMemoryAnalysisRepository
from app.repositories.base import (
    AnalysisRepository,
    JobRepository,
    ProfileRepository,
    RoadmapRepository,
)
from app.repositories.job_repo import InMemoryJobRepository
from app.repositories.profile_repo import InMemoryProfileRepository
from app.repositories.roadmap_repo import InMemoryRoadmapRepository

logger = logging.getLogger(__name__)

_EXT_KEY = "skillbridge"


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------


def pick_backend(config) -> str:
    """Pick the repository backend for *config*.

    Returns one of ``"memory"``, ``"sqlite"``, or ``"postgres"``.

    Args:
        config: A config instance or class exposing ``REPO_BACKEND`` and
            ``DATABASE_URL`` attributes.

    Raises:
        RuntimeError: When ``DATABASE_URL`` uses a scheme other than
            ``sqlite:`` or ``postgresql:`` (and ``REPO_BACKEND`` isn't
            set to override).
    """
    explicit = str(getattr(config, "REPO_BACKEND", "") or "").strip()
    if explicit:
        if explicit not in {"memory", "sqlite", "postgres"}:
            raise RuntimeError(
                f"Unsupported REPO_BACKEND {explicit!r}; "
                f"expected one of 'memory', 'sqlite', 'postgres'"
            )
        return explicit

    url = str(getattr(config, "DATABASE_URL", "") or "").strip()
    if not url:
        return "memory"

    scheme = url.split(":", 1)[0].split("+", 1)[0]
    if scheme == "sqlite":
        return "sqlite"
    if scheme == "postgresql":
        return "postgres"

    raise RuntimeError(
        f"Unsupported DATABASE_URL scheme {scheme!r}; "
        f"expected one of 'sqlite:', 'postgresql:' (or set REPO_BACKEND)"
    )


# ---------------------------------------------------------------------------
# Extensions container
# ---------------------------------------------------------------------------


@dataclass
class Extensions:
    """Container for per-app singletons.

    Each :func:`app.create_app` call produces its own :class:`Extensions`
    instance, so test apps stay isolated from each other (R10.2).

    Repository fields are typed as the Phase 1 :mod:`app.repositories.base`
    Protocols so that either the ``InMemory*`` or ``SqlAlchemy*``
    families structurally fit (R2.1, R2.2).
    """

    profile_repo: ProfileRepository
    job_repo: JobRepository
    analysis_repo: AnalysisRepository
    roadmap_repo: RoadmapRepository
    taxonomy: list[str]
    resources: list[LearningResource]
    categorizer: SkillCategorizerInterface

    # Phase 2: SQL backend handles. Both are ``None`` on memory-backed
    # apps; handlers never touch them directly.
    engine: Engine | None = None
    session_factory: sessionmaker[Session] | None = None

    # Diagnostic breadcrumbs — what paths/URLs were used at init.
    # `_database_url` is kept for introspection in tests only; it must
    # not leak into responses, logs, or error bodies (R10.1).
    _jobs_path: str = field(default="")
    _taxonomy_path: str = field(default="")
    _resources_path: str = field(default="")
    _backend: str = field(default="memory")
    _database_url: str = field(default="", repr=False)


# ---------------------------------------------------------------------------
# Categorizer selection (unchanged from Phase 1)
# ---------------------------------------------------------------------------


def _select_categorizer(app: Flask) -> SkillCategorizerInterface:
    """Pick the categorizer, respecting TestConfig's forced fallback.

    TestConfig sets ``GROQ_API_KEY = ""``; the factory must honour that
    even if the process env has a real key (Phase 1 R10.3). We
    temporarily clear the env var around :func:`get_categorizer` to
    avoid any fallback to environment-based lookup inside ai_engine.
    """
    configured_key = str(app.config.get("GROQ_API_KEY", "") or "")
    if not configured_key:
        saved = os.environ.pop("GROQ_API_KEY", None)
        try:
            return FallbackCategorizer()
        finally:
            if saved is not None:
                os.environ["GROQ_API_KEY"] = saved

    return get_categorizer()


# ---------------------------------------------------------------------------
# Per-backend builders
# ---------------------------------------------------------------------------


def _build_memory_extensions(app: Flask) -> Extensions:
    """Phase 1 flow: in-memory repositories over JSON data."""
    jobs_path = app.config["JOBS_PATH"]
    taxonomy_path = app.config["TAXONOMY_PATH"]
    resources_path = app.config["RESOURCES_PATH"]

    jobs = load_jobs(jobs_path)
    taxonomy = load_taxonomy(taxonomy_path)
    resources = _load_resources(resources_path)

    return Extensions(
        profile_repo=InMemoryProfileRepository(),
        job_repo=InMemoryJobRepository(jobs),
        analysis_repo=InMemoryAnalysisRepository(),
        roadmap_repo=InMemoryRoadmapRepository(),
        taxonomy=taxonomy,
        resources=resources,
        categorizer=_select_categorizer(app),
        engine=None,
        session_factory=None,
        _jobs_path=jobs_path,
        _taxonomy_path=taxonomy_path,
        _resources_path=resources_path,
        _backend="memory",
        _database_url="",
    )


def _build_sql_extensions(app: Flask, backend: str) -> Extensions:
    """Build a SQL-backed Extensions bundle.

    Stage C wires the engine, sessionmaker, and the
    (taxonomy/resources/categorizer) side of things — the repository
    instances themselves are still :class:`InMemory*` placeholders
    here; Stage F swaps in the :class:`SqlAlchemy*` concretes.

    This staged approach lets Stage C's test gate verify the backend
    selector, engine factory, and session wiring in isolation without
    blocking on repository code that doesn't exist yet.

    Raises:
        NotImplementedError: The SQL branch is wired for engine/session
            but Stage F hasn't added the Sql repositories yet. Any
            config that actually selects a SQL backend (including
            ``create_app("test_sql")``) will hit this until Stage F.
    """
    raise NotImplementedError(
        f"SQL backend {backend!r} selected but SqlAlchemy repositories "
        "land in Phase 2 Stage F. Wire them in _build_sql_extensions "
        "once the four SqlAlchemy*Repository classes exist."
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def init_extensions(app: Flask) -> None:
    """Build the per-app :class:`Extensions` bundle and stash it.

    Dispatches to the memory or SQL builder based on
    :func:`pick_backend`. The result is stored on
    ``app.extensions["skillbridge"]``.
    """
    backend = pick_backend(app.config)

    if backend == "memory":
        ext = _build_memory_extensions(app)
    else:
        ext = _build_sql_extensions(app, backend)

    # Install (or clear) the module-level sessionmaker in db.session so
    # repository code can reach for it later. Clearing on memory-backed
    # apps protects any misconfigured SQL repo from silently using a
    # leftover factory from an earlier test app.
    set_session_factory(ext.session_factory)

    app.extensions[_EXT_KEY] = ext

    logger.info(
        "extensions.ready",
        extra={"extra_fields": {
            "backend": ext._backend,
            "taxonomy": len(ext.taxonomy),
            "resources": len(ext.resources),
            "categorizer": type(ext.categorizer).__name__,
        }},
    )


def get_ext(app: Flask | None = None) -> Extensions:
    """Return the Extensions bundle for *app* (defaults to current_app)."""
    target = app if app is not None else current_app
    return target.extensions[_EXT_KEY]
