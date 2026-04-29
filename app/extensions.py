"""Process-wide singletons attached to a Flask app.

``init_extensions(app)`` loads the three JSON data files once at
startup (jobs, skill taxonomy, learning resources), instantiates the
four repositories, and picks the categorizer via
:func:`app.core.ai_engine.get_categorizer`. The result is stashed on
``app.extensions["skillbridge"]`` so blueprints can reach it through
:func:`get_ext` without global state.

Design reference: `.kiro/specs/phase-1-rest-api/design.md` §Extensions.
Requirement reference: R10.1, R10.2, R10.3, R10.4.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from flask import Flask, current_app

from app.core.ai_engine import FallbackCategorizer, SkillCategorizerInterface, get_categorizer
from app.core.job_catalog import load_jobs
from app.core.models import LearningResource
from app.core.resume_parser import load_taxonomy
from app.core.roadmap_generator import _load_resources
from app.repositories.analysis_repo import InMemoryAnalysisRepository
from app.repositories.job_repo import InMemoryJobRepository
from app.repositories.profile_repo import InMemoryProfileRepository
from app.repositories.roadmap_repo import InMemoryRoadmapRepository

logger = logging.getLogger(__name__)

_EXT_KEY = "skillbridge"


@dataclass
class Extensions:
    """Container for per-app singletons.

    Each :func:`app.create_app` call produces its own :class:`Extensions`
    instance, so test apps stay isolated from each other (R10.2).
    """

    profile_repo: InMemoryProfileRepository
    job_repo: InMemoryJobRepository
    analysis_repo: InMemoryAnalysisRepository
    roadmap_repo: InMemoryRoadmapRepository
    taxonomy: list[str]
    resources: list[LearningResource]
    categorizer: SkillCategorizerInterface
    # Keep lists of names loaded, useful for diagnostics without reading
    # files again.
    _jobs_path: str = field(default="")
    _taxonomy_path: str = field(default="")
    _resources_path: str = field(default="")


def _select_categorizer(app: Flask) -> SkillCategorizerInterface:
    """Pick the categorizer, respecting TestConfig's forced fallback.

    TestConfig sets ``GROQ_API_KEY = ""``; the factory must honour that
    even if the process env has a real key (R10.3). We temporarily clear
    the env var around :func:`get_categorizer` to avoid any fallback to
    environment-based lookup inside ai_engine.
    """
    configured_key = str(app.config.get("GROQ_API_KEY", "") or "")
    if not configured_key:
        # Force fallback for deterministic tests. Save/restore the env var
        # so we don't mutate global state across apps.
        saved = os.environ.pop("GROQ_API_KEY", None)
        try:
            return FallbackCategorizer()
        finally:
            if saved is not None:
                os.environ["GROQ_API_KEY"] = saved

    # Non-test configs: honour whatever ai_engine's factory decides
    # (GroqCategorizer if the key works, else its own FallbackCategorizer).
    return get_categorizer()


def init_extensions(app: Flask) -> None:
    """Load data, instantiate repos + categorizer, store on the app."""
    jobs_path = app.config["JOBS_PATH"]
    taxonomy_path = app.config["TAXONOMY_PATH"]
    resources_path = app.config["RESOURCES_PATH"]

    jobs = load_jobs(jobs_path)
    taxonomy = load_taxonomy(taxonomy_path)
    resources = _load_resources(resources_path)

    ext = Extensions(
        profile_repo=InMemoryProfileRepository(),
        job_repo=InMemoryJobRepository(jobs),
        analysis_repo=InMemoryAnalysisRepository(),
        roadmap_repo=InMemoryRoadmapRepository(),
        taxonomy=taxonomy,
        resources=resources,
        categorizer=_select_categorizer(app),
        _jobs_path=jobs_path,
        _taxonomy_path=taxonomy_path,
        _resources_path=resources_path,
    )

    app.extensions[_EXT_KEY] = ext

    logger.info(
        "extensions.ready",
        extra={"extra_fields": {
            "jobs": len(jobs),
            "taxonomy": len(taxonomy),
            "resources": len(resources),
            "categorizer": type(ext.categorizer).__name__,
        }},
    )


def get_ext(app: Flask | None = None) -> Extensions:
    """Return the Extensions bundle for *app* (defaults to current_app)."""
    target = app if app is not None else current_app
    return target.extensions[_EXT_KEY]
