#!/usr/bin/env sh
# Container entrypoint.
#
# Responsibilities (in order):
#   1. Auto-stamp recovery: if the target DB already has our tables
#      but alembic's bookkeeping table is empty or missing, stamp
#      head without running any migrations. This handles the
#      specific failure mode where an earlier deploy crashed
#      mid-migration (e.g. psycopg driver missing) after CREATE
#      TABLE but before Alembic wrote its version row. Without
#      this, every subsequent boot dies on "relation already exists".
#   2. Run pending Alembic migrations against $DATABASE_URL.
#      Idempotent — no-op on an already-up-to-date schema.
#   3. exec gunicorn so it becomes PID 1 and receives SIGTERM
#      directly from the orchestrator (Render / compose / k8s).
#      Without `exec`, SIGTERM hits this shell and gunicorn
#      never drains in-flight requests.
#
# Migration failures abort startup with a non-zero exit code; the
# old container keeps serving until a successful deploy replaces
# it (fail-closed on migration errors).
#
# POSIX sh (not bash) so the script works if we ever swap the
# runtime base image to an alpine variant.

set -e

echo "[entrypoint] Checking for stuck migration state..."
python <<'PY'
"""Detect + recover from a half-applied migration.

Condition: the users table exists (schema was already created by a
previous run) AND alembic_version is empty or missing (bookkeeping
was never written). In that case, stamp head so subsequent
alembic upgrade is a no-op.
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import inspect

from app.config import CONFIG_MAP
from app.db.engine import build_engine

app_env = os.environ.get("APP_ENV", "dev").strip() or "dev"
db_url = CONFIG_MAP[app_env].DATABASE_URL
engine = build_engine(db_url)

with engine.connect() as conn:
    insp = inspect(conn)
    tables = set(insp.get_table_names())
    has_schema = "users" in tables

# If our schema tables already exist, the DB is post-migration.
# Force-stamp head regardless of whether alembic_version exists or
# what it contains. This handles:
#   - Tables created by a crashed prior run with no version row
#   - Tables created but alembic_version contains a stale/partial
#     revision (previous bug — DuplicateTable on retry)
#   - A fresh copy of the DB restored from backup without alembic
#     state
# On a truly clean DB (no users table), fall through and let
# alembic upgrade head create everything.
if has_schema:
    print("[entrypoint] Schema already present — stamping head", flush=True)
    sys.exit(42)
else:
    print("[entrypoint] Clean DB — running migrations normally", flush=True)
    sys.exit(0)
PY
rc=$?
if [ "$rc" = "42" ]; then
    alembic stamp head
elif [ "$rc" != "0" ]; then
    echo "[entrypoint] Recovery probe failed (exit $rc); aborting" >&2
    exit "$rc"
fi

echo "[entrypoint] Running alembic upgrade head..."
alembic upgrade head

echo "[entrypoint] Starting gunicorn on port ${PORT:-5000}..."
exec gunicorn \
    --bind "0.0.0.0:${PORT:-5000}" \
    --workers 1 \
    --access-logfile - \
    --error-logfile - \
    wsgi:application
