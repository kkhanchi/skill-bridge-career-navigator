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

from sqlalchemy import inspect, text

from app.config import CONFIG_MAP
from app.db.engine import build_engine

app_env = os.environ.get("APP_ENV", "dev").strip() or "dev"
db_url = CONFIG_MAP[app_env].DATABASE_URL
engine = build_engine(db_url)

with engine.connect() as conn:
    insp = inspect(conn)
    tables = set(insp.get_table_names())
    has_schema = "users" in tables
    has_alembic = "alembic_version" in tables
    needs_stamp = False
    if has_schema and not has_alembic:
        needs_stamp = True
    elif has_schema and has_alembic:
        row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
        if row is None:
            needs_stamp = True

if needs_stamp:
    print("[entrypoint] Detected stuck migration — stamping head", flush=True)
    sys.exit(42)
else:
    print("[entrypoint] Migration state is clean", flush=True)
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
