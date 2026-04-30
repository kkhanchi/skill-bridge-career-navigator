"""Idempotent seed script for the jobs catalog.

Reads ``data/jobs.json``, computes slug ids with the exact same logic
as :class:`InMemoryJobRepository` (so Phase 1 cached `job_id` values
still resolve after the DB lands), and upserts rows into the `jobs`
table. Safe to re-run against an unchanged `jobs.json`.

Usage::

    APP_ENV=dev python -m scripts.seed_db
    APP_ENV=prod DATABASE_URL=postgresql://... python -m scripts.seed_db

Exits with status 0 on success, 1 on any failure; all changes are
made inside a single transaction so a failed run never commits
partial data (R5.6).

Design reference: `.kiro/specs/phase-2-persistence/design.md` §Seed script algorithm.
Requirement reference: R5.1, R5.2, R5.3, R5.5, R5.6, R10.2.
"""

from __future__ import annotations

import logging
import os
import sys

from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.config import CONFIG_MAP
from app.core.job_catalog import load_jobs
from app.core.models import JobPosting
from app.db.engine import build_engine
from app.db.models import JobORM
from app.repositories.job_repo import InMemoryJobRepository

logger = logging.getLogger(__name__)


def _resolve_engine() -> Engine:
    """Build an engine from the config selected by APP_ENV."""
    app_env = os.environ.get("APP_ENV", "dev").strip() or "dev"
    if app_env not in CONFIG_MAP:
        raise RuntimeError(
            f"Unknown APP_ENV {app_env!r}; expected one of {sorted(CONFIG_MAP)}"
        )
    config = CONFIG_MAP[app_env]
    url = str(getattr(config, "DATABASE_URL", "") or "").strip()
    if not url:
        raise RuntimeError(
            f"DATABASE_URL is empty on APP_ENV={app_env!r}; set it in the "
            f"environment before running seed_db."
        )
    return build_engine(url)


def _slugged_jobs(jobs: list[JobPosting]) -> list[tuple[str, JobPosting]]:
    """Return ``(slug, job)`` pairs matching InMemoryJobRepository.

    Reuses the in-memory repo's slug + disambiguation logic so the DB
    ends up with the same ids a Phase 1 runtime would produce (R5.4).
    """
    repo = InMemoryJobRepository(jobs)
    pairs: list[tuple[str, JobPosting]] = []
    # InMemoryJobRepository stores `_records` in load order; we walk
    # it directly rather than going through `list()` so pagination /
    # ordering doesn't bleed into the seed path.
    for record in repo._records:  # type: ignore[attr-defined]
        pairs.append((record.id, record.job))
    return pairs


def seed_db(engine: Engine | None = None, *, jobs_path: str | None = None) -> int:
    """Perform the seed. Returns the count of rows touched.

    Args:
        engine: Optional pre-built engine (tests pass one to avoid the
            env lookup). Default: resolve from APP_ENV.
        jobs_path: Optional jobs.json path (tests override). Default:
            resolve from the active config's JOBS_PATH.
    """
    if engine is None:
        engine = _resolve_engine()

    if jobs_path is None:
        app_env = os.environ.get("APP_ENV", "dev").strip() or "dev"
        config = CONFIG_MAP[app_env]
        jobs_path = str(getattr(config, "JOBS_PATH", ""))

    jobs = load_jobs(jobs_path)
    pairs = _slugged_jobs(jobs)

    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    touched = 0
    with SessionLocal() as session:
        for slug, job in pairs:
            existing = session.get(JobORM, slug)
            if existing is None:
                session.add(
                    JobORM(
                        id=slug,
                        title=job.title,
                        description=job.description,
                        required_skills=list(job.required_skills),
                        preferred_skills=list(job.preferred_skills),
                        experience_level=job.experience_level,
                    )
                )
            else:
                # Refresh content fields. Slug (primary key) is never
                # changed — R5.3 explicitly requires id stability.
                existing.title = job.title
                existing.description = job.description
                existing.required_skills = list(job.required_skills)
                existing.preferred_skills = list(job.preferred_skills)
                existing.experience_level = job.experience_level
            touched += 1
        session.commit()

    return touched


def main() -> int:
    """CLI entry point. Returns process exit code."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        count = seed_db()
    except Exception as err:  # noqa: BLE001 - we want to surface any failure
        # R10.2: never print DATABASE_URL. Only surface the driver
        # family so an operator can tell if it's a SQLite vs Postgres
        # misconfiguration.
        app_env = os.environ.get("APP_ENV", "dev")
        logger.error("seed_db failed on APP_ENV=%s: %s", app_env, err)
        return 1
    logger.info("seed_db ok — %d job rows touched", count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
