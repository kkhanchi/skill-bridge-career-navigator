# SkillBridge developer quality gate.
#
# Run from this directory (the git repo root). `make check`
# mirrors CI exactly, so a green local run predicts a green CI run.

.PHONY: install hooks lint format format-check typecheck test check clean

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
