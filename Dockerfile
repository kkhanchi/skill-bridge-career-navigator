# syntax=docker/dockerfile:1.7
#
# Multi-stage build for the SkillBridge backend.
#
# - `builder` installs Python dependencies (incl. anything with C
#   extensions) using build-essential + libpq-dev. The venv-like
#   install directory is copied into the runtime stage; nothing
#   else from builder survives.
# - `runtime` ships only what's needed at serve time: python-slim,
#   libpq5 (for psycopg), the installed packages, and the
#   application source. No pip, no compilers, no test deps.
#
# Target image size: < 250 MB uncompressed. See ADR-019.


# ===== builder =====
FROM python:3.12-slim AS builder

# Build-time deps for packages with C extensions:
# - argon2-cffi ships its own bundled C code but needs a compiler
# - psycopg[binary] ships prebuilt wheels so libpq-dev is
#   technically optional, but we keep it for deterministic rebuilds
#   if a future phase switches to psycopg's source distribution
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy ONLY the requirements file first. If source code changes
# without requirements changes, Docker reuses this cached layer.
# Swap the order here and every commit invalidates the expensive
# dependency install.
COPY requirements.txt ./

# --prefix=/install places the full Python environment
# (bin + lib/python3.12/site-packages) into /install, which the
# runtime stage copies wholesale into /usr/local.
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ===== runtime =====
FROM python:3.12-slim AS runtime

# Non-root user with a fixed UID so file permissions are
# predictable across builds and across any future volume mounts.
# Running as UID 10001 (a "system" user range convention) is
# defense-in-depth: if the container is compromised, the attacker
# doesn't start with root inside the container.
RUN groupadd --system --gid 10001 skillbridge \
    && useradd --system --uid 10001 --gid 10001 --create-home skillbridge

# Runtime-only libpq for psycopg's database connections.
# build-essential is NOT installed here — the builder stage already
# produced everything that needs compiling.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy the installed Python environment from the builder stage.
# /usr/local is the conventional prefix for Python's system install
# on Debian/Ubuntu-derived images so this "just works" for `python`,
# `pip`, `alembic`, `gunicorn`, etc. on the PATH.
COPY --from=builder /install /usr/local

WORKDIR /app

# Application source. --chown so the non-root user owns the files —
# avoids surprises if a future stage needs to write inside /app
# (e.g. generated files, caches).
COPY --chown=skillbridge:skillbridge . /app

# Make the entrypoint executable BEFORE switching to the non-root
# user (root can chmod +x any file; skillbridge couldn't).
RUN chmod +x /app/entrypoint.sh

USER skillbridge

# PORT default for compose parity; Render overrides at runtime.
# PYTHONUNBUFFERED so print/logging goes straight to stdout (matters
# for container log streaming — buffered output would only flush
# on shutdown).
# PYTHONDONTWRITEBYTECODE because read-only container filesystems
# and .pyc files don't mix; we don't need the startup speedup.
ENV PORT=5000 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Documentation only — Render reads $PORT at runtime. compose
# publishes 5000:5000 explicitly.
EXPOSE 5000

# Signal handling: entrypoint.sh uses `exec gunicorn`, so gunicorn
# becomes PID 1 and receives SIGTERM directly.
ENTRYPOINT ["/app/entrypoint.sh"]
