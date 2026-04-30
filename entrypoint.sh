#!/usr/bin/env sh
# Container entrypoint.
#
# Responsibilities (in order):
#   1. Run pending Alembic migrations against $DATABASE_URL.
#      Idempotent — no-op on an already-up-to-date schema.
#   2. exec gunicorn so it becomes PID 1 and receives SIGTERM
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

echo "[entrypoint] Running alembic upgrade head..."
alembic upgrade head

echo "[entrypoint] Starting gunicorn on port ${PORT:-5000}..."
exec gunicorn \
    --bind "0.0.0.0:${PORT:-5000}" \
    --workers 1 \
    --access-logfile - \
    --error-logfile - \
    wsgi:application
