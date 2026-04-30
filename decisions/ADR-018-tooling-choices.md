# ADR-018: Phase 4 tooling choices — Ruff, mypy, pytest-cov, factory-boy, GitHub Actions, Makefile

- **Status:** Accepted
- **Date:** 2026-04-30
- **Phase:** 4 — Testing & Quality

## Context

Phase 4's goal is to formalize the development loop around the code
shipped in Phases 1–3. That means picking tools for six orthogonal
concerns: linting, formatting, type checking, coverage measurement,
test data generation, and CI. Six tools, six small decisions —
consolidated here as one ADR because they form a coherent stack, not
six independent choices.

## Decision

### Linting + Formatting: Ruff (over Black + isort + flake8)

- Single tool covering pycodestyle (`E`/`W`), Pyflakes (`F`), isort
  (`I`), flake8-bugbear (`B`), pyupgrade (`UP`), and flake8-simplify
  (`SIM`) rule families. One `pyproject.toml` section instead of
  three config files.
- Order-of-magnitude faster than the Black+isort+flake8 trio on a
  suite our size (seconds vs tens of seconds).
- Ruff's formatter is Black-compatible in practice — the output is
  indistinguishable from Black for Phase 1/2/3 code.

**Ignored rules, with reasons in the config:** `E501` (formatter
handles line length), `B008` (Flask decorators legitimately take
function calls as arguments), `SIM108` (terse ternaries hurt
readability in `roadmap_generator.py`'s phase-index math),
`SIM105` (`contextlib.suppress` obscures the swallow-intent in the
session teardown hook), `UP047` (PEP 695 generic syntax isn't
universally supported by downstream tooling yet).

### Type checking: mypy (over Pyright)

- Pyright is faster and has better IDE integration but ships as a
  Node package; running it in CI means installing Node in every
  GitHub Actions run. mypy is a Python package, installs alongside
  the rest of `requirements.txt`, and runs inline with pytest.
- `strict = true` globally across `app/` forces every new function
  to be annotated.
- Per-module escape hatches:
  - `app.core.ai_engine` — full `ignore_errors`. The Groq SDK has no
    type stubs and the module's branches are integration-tested,
    not type-tested. Typing this path would require shipping our
    own stubs; out of Phase 4's scope.
  - `app.api.v1.*` handler modules — relax `no-untyped-def` and
    `untyped-decorator`. Flask view-handler chains
    (`@bp.post + @require_auth + @_with_limit + @validate_body`)
    don't propagate types cleanly under strict mode; the payoff of
    annotating every handler's return (`tuple[flask.Response, int]`)
    is low and the mypy noise would be high. Runtime behaviour
    stays integration-tested.
  - Root-level Streamlit shim modules (`ai_engine.py`,
    `gap_analyzer.py`, etc.) — `ignore_errors`. Legacy Phase 1
    wrappers; cleanup is a Phase 5+ candidate.

### Coverage: pytest-cov (over coverage.py directly)

- pytest-cov integrates with `addopts` in `pyproject.toml`. Plain
  `pytest` runs with coverage instrumentation AND the 80% floor,
  matching CI exactly without extra flags.
- coverage.py directly would require a separate `coverage run pytest`
  invocation, which splits config between two places
  (`pyproject.toml` for the coverage settings, a script or Makefile
  target for the invocation).
- Branch coverage enabled (`branch = true` in `[tool.coverage.run]`).
  A missed decision branch counts the same as a missed statement —
  catches `if x:` without a test on the False side.

### Coverage floor: 80%

- Current state is 91%. The 80% floor gives room for realistic
  Phase 5+ additions (new endpoints, new business logic) without
  tripping CI on every PR, while still blocking regressions that
  shed five or ten points of coverage at once.
- Dropping below 80% is a CI fail, not a warning. The signal
  MUST be loud enough to force investigation.

### Test data: factory-boy over hand-rolled fixtures

- ~25 SQL-backed tests already exist. Adding another 5 in Phase 5+
  pushes us past the threshold where `factory.SubFactory` +
  `factory.Sequence` + `Faker` integration beats per-test helpers.
- `factory.Factory` (not `factory.alchemy.SQLAlchemyModelFactory`)
  because the suite has both memory- and SQL-backed tests. A
  SQLAlchemy-bound factory would require a session at construction
  time, colliding with memory-backed tests. Plain factories produce
  detached instances; the test decides whether to `session.add`.
- One factory per ORM model (6 total). Round-trip tests in
  `test_factories.py` assert the detached instances survive
  commit + expire + reload.

### Developer command surface: Makefile (over invoke / just / taskfile)

- Five targets (`lint`, `format`, `typecheck`, `test`, `check`),
  plus housekeeping (`install`, `hooks`, `clean`).
- Universally available — no extra install cost.
- `just` and `taskfile` would be better for complex multi-argument
  commands, but Phase 4 has none. Make is the right size.

### CI: GitHub Actions

- The repo lives on GitHub. Any other CI choice would add a second
  account, a second billing surface, a second set of credentials.
- Single workflow (`ci.yml`) with one job (`quality-gate`) running
  four steps (lint, format-check, mypy, pytest). No build or
  deploy stage — that's Phase 5.
- Concurrency control cancels in-progress runs on the same branch
  when a new push lands. Keeps the Actions queue clean on
  rapid-push branches.
- Coverage XML uploaded as a workflow artifact (`if: always()`) so
  a failing run still surfaces the coverage report for inspection.

### Pre-commit: Ruff + whitespace hooks, no pytest

- Pre-commit budget is <1s. Tests run in ~10s.
- Hooks: `ruff --fix`, `ruff-format`, `trailing-whitespace`,
  `end-of-file-fixer`, `check-yaml`, `check-added-large-files`.
- Ruff pre-commit pinned to `v0.15.12` — matches the CLI version in
  `requirements.txt` so the hook and CLI agree on formatter output.
  Version drift here leads to cycles of "commit fails → format →
  commit fails again" as the two versions disagree on trivia.

## Consequences

**Easier:**

- One quality gate command (`make check`) locally and in CI. Green
  local → green CI, every time.
- New code MUST be strictly typed (mypy) and MUST stay above 80%
  coverage. Regressions in either are blocking.
- Future refactors have a safety net: the 274-test suite + strict
  mypy + coverage floor catch the vast majority of mechanical
  breakage before review.

**Harder:**

- Adding a new feature requires writing tests for it (to stay
  above 80%) AND annotating it (to satisfy mypy). That's the
  intent, not a bug, but raising the bar slows the "I just want
  to land a quick change" path.
- Six dev dependencies (`ruff`, `mypy`, `pytest-cov`, `pre-commit`,
  `factory-boy`, `Faker`) + their transitives. Install-cost grew
  from Phase 3's minimal set.
- mypy's strict mode and Flask's untyped decorator chain don't
  cooperate gracefully. The per-module overrides in pyproject.toml
  are scar tissue from that friction.

**Constrained:**

- Upgrading Ruff or mypy requires simultaneously updating the
  pinned versions in `requirements.txt`, `.pre-commit-config.yaml`,
  and (for Ruff) re-running the formatter if the new version
  disagrees on output. Pin carefully; plan bumps.
- The 80% floor is a commitment. Every PR that drops below it must
  either add tests, exclude the new code in
  `[tool.coverage.run].omit` with justification, or raise the
  threshold. No silent downgrades.

## Alternatives considered and rejected

- **Black + isort + flake8**: superseded by Ruff.
- **Pyright**: Node dependency in CI; uses per-file config that
  we'd have to bridge to `pyproject.toml`.
- **coverage.py standalone**: config split between files.
- **Hand-rolled fixtures only**: fine at 10 SQL tests, painful at
  30+. Switching later would churn more tests than switching now.
- **invoke / just / taskfile**: overkill for five targets.
- **CircleCI / GitLab CI**: repo is on GitHub.
- **Codecov / Coveralls**: deferred to Phase 5+ when we have PR
  preview deploys that make coverage deltas meaningful.
