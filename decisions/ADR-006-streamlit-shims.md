# ADR-006: Streamlit UI kept via root-level shims during Phase 1

- **Status:** Accepted
- **Date:** 2026-04-30
- **Phase:** 1 — REST API Foundation

## Context

The SkillBridge prototype is a Streamlit app at `skill-bridge/app.py`
that imports directly from sibling modules: `from profile_manager import
create_profile`, `from models import UserProfile`, etc. Phase 1
reorganizes those modules under `app/core/` so they stop being siblings
of the Streamlit script.

Two migration paths:

1. **Rewrite the Streamlit UI immediately** to call the HTTP API via
   `requests`. Clean end state, but widens Phase 1's scope and risks
   breaking a working reference frontend during a foundation-laying
   phase.
2. **Keep the UI importing from root-level shims** that re-export the
   core modules. The UI runs unchanged; the HTTP cutover becomes an
   optional Phase-1 exit step or a Phase-2 task.

Also nested: where does `models.py` live? Keeping it at the root
preserves simplicity; moving it under `app/core/` makes the package
boundary honest. The shim approach resolves both questions the same
way.

## Decision

**Keep the Streamlit UI working via root-level shims for the duration
of Phase 1.** For each of the 8 moved modules
(`models`, `profile_manager`, `resume_parser`, `job_catalog`,
`gap_analyzer`, `ai_engine`, `roadmap_generator`, `profile_printer`)
leave a 2-line file at the repository root that reads:

```python
"""Shim: re-exports `app.core.X` for the existing Streamlit UI."""
from app.core.X import *  # noqa: F401,F403
```

`models.py` moves into `app/core/models.py` — the root shim handles
the `from models import UserProfile` imports used by `app.py` and
the existing unit test fixtures. Both classes of caller run
unmodified.

The HTTP cutover (replacing `from profile_manager import create_profile`
with `requests.post(...)`) is explicitly **out of scope for Phase 1**
per `plan.md`. If Phase 1 ends with time to spare, task 71 does a
manual Streamlit smoke test; otherwise cutover moves into Phase 2.

## Consequences

**Easier:**

- Zero regression risk on a working reference frontend. The 3
  existing `tests/unit/test_gap_analysis.py` tests pass unchanged,
  confirmed at every stage gate.
- Phase 1 stays focused. The API is built, tested, and shipped
  without also rewriting a Streamlit UI that doesn't yet call it.
- Import surface stays backward compatible. Any external notebook or
  script that ever did `from skill_bridge.profile_manager import
  create_profile` keeps working (modulo sys.path tricks they were
  doing anyway).

**Harder:**

- Two import paths coexist. The API imports via `from
  app.core.profile_manager import create_profile`; the UI still
  imports via `from profile_manager import create_profile`. Pylance
  / mypy can sometimes get confused about which is "the" module for
  a given symbol. The `# noqa: F401,F403` hides the starred-import
  warnings from ruff.

**Constrained:**

- Exit criterion for removing the shims: the Streamlit UI calls the
  API over HTTP instead of importing core modules. That's a Phase 2
  task (or a Phase 1 stretch task if calendar allows) — not Phase 1
  critical path. When it lands, the eight root shim files get
  deleted in one commit.
- `ai_engine.py` resolves `.env` via `Path(__file__).resolve().parents[2]`
  because the module now lives two levels deep; if anyone ever moves
  it back to the root, that path math needs updating.
