#!/usr/bin/env sh
# Container entrypoint.
#
# Responsibilities:
#   1. Run alembic upgrade head against $DATABASE_URL.
#      If the upgrade fails AND the failure is our known stuck
#      state (schema already present), stamp head and move on.
#   2. exec gunicorn so it receives SIGTERM directly.
#
# POSIX sh so this works on any base image.

set -e

echo "[entrypoint v2] === container starting ==="
echo "[entrypoint v2] APP_ENV=${APP_ENV:-unset} PORT=${PORT:-unset}"

# Run the upgrade. If it fails, check whether the DB is in the
# known stuck state (schema tables present). If so, stamp head
# and retry the upgrade (which will now be a no-op and exit
# cleanly). If not, propagate the failure.
set +e
echo "[entrypoint v2] Running: alembic upgrade head"
alembic upgrade head
upgrade_rc=$?
set -e

if [ "$upgrade_rc" != "0" ]; then
    echo "[entrypoint v2] alembic upgrade exited $upgrade_rc — checking for stuck state"
    python - <<'PY'
"""Probe the DB. If our schema exists, stamp head and exit 0 so the
shell retries the upgrade. Otherwise exit 1 so the shell aborts."""

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
    tables = set(inspect(conn).get_table_names())

if "users" in tables:
    print("[entrypoint v2] DB has schema; will stamp head", flush=True)
    sys.exit(0)
else:
    print("[entrypoint v2] DB has no schema; upgrade failed for another reason", flush=True)
    sys.exit(1)
PY
    probe_rc=$?
    if [ "$probe_rc" = "0" ]; then
        echo "[entrypoint v2] Stamping alembic to head"
        alembic stamp head
        echo "[entrypoint v2] Re-running alembic upgrade head (no-op expected)"
        alembic upgrade head
    else
        echo "[entrypoint v2] Fatal: alembic failed and DB is not in stuck state"
        exit "$upgrade_rc"
    fi
fi

echo "[entrypoint v2] Seeding jobs catalog (idempotent)"
# seed_db.py is idempotent — reruns against an unchanged jobs.json
# are a no-op. Run it on every boot so an empty DB (fresh Render
# deploy) gets populated without manual intervention. Failures are
# logged but don't abort startup; the API still serves without
# catalog rows (just shows an empty list).
set +e
python -m scripts.seed_db
seed_rc=$?
set -e
if [ "$seed_rc" != "0" ]; then
    echo "[entrypoint v2] WARNING: seed script exited $seed_rc — continuing anyway"
fi

echo "[entrypoint v2] Starting gunicorn on 0.0.0.0:${PORT:-5000}"
exec gunicorn \
    --bind "0.0.0.0:${PORT:-5000}" \
    --workers 1 \
    --access-logfile - \
    --error-logfile - \
    wsgi:application
