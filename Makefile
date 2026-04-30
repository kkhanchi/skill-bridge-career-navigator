# SkillBridge developer quality gate.
#
# Run from this directory (the git repo root). `make check`
# mirrors CI exactly, so a green local run predicts a green CI run.

.PHONY: install hooks lint format format-check typecheck test check clean \
	docker-build compose-up compose-down compose-logs smoke

# One-time setup.
install:
	pip install -r requirements.txt

# Install the pre-commit git hooks. Re-run if you change
# .pre-commit-config.yaml.
hooks:
	pre-commit install

# Ruff lint — catches style + likely-bug patterns.
lint:
	ruff check app/ tests/

# Apply Ruff formatting.
format:
	ruff format app/ tests/

# Verify Ruff formatting without mutating files. CI uses this form.
format-check:
	ruff format --check app/ tests/

# Strict mypy across app/.
typecheck:
	mypy app/

# Full pytest run with branch coverage and the 80% floor.
test:
	pytest tests/

# Full quality gate: lint -> format check -> typecheck -> test.
# Any failure aborts subsequent steps.
check: lint format-check typecheck test
	@echo "All checks passed."

# Best-effort cleanup of tool artifacts. pyproject.toml keeps them
# gitignored too.
clean:
	rm -rf .ruff_cache .mypy_cache .pytest_cache coverage.xml .coverage


# ---------------------------------------------------------------------------
# Phase 5 — Docker + compose targets
# ---------------------------------------------------------------------------
#
# These targets invoke the Docker CLI directly. They assume
# `docker` is on PATH; if not, install Docker Desktop (macOS/Win)
# or docker-ce (Linux) first.

# Build the application image from the local Dockerfile.
docker-build:
	docker build -t skill-bridge:local -f Dockerfile .

# Bring the compose stack up (API + Postgres) in the background.
compose-up:
	docker compose up -d --build
	@echo "API starting. Run 'make smoke' once it's ready (~10s)."

# Tear down the compose stack. Use `compose down -v` manually to
# wipe the postgres_data volume too.
compose-down:
	docker compose down

# Tail both services' logs.
compose-logs:
	docker compose logs -f

# Lightweight readiness probe — hits /health and fails loudly if
# the container isn't up. Run after compose-up.
smoke:
	@echo "Hitting http://localhost:5000/health ..."
	@curl --silent --show-error --fail http://localhost:5000/health
	@echo ""
	@echo "OK"
