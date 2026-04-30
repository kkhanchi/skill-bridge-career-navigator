# Architecture Decision Records

This directory holds ADRs — short records of non-trivial design
decisions made during the evolution of SkillBridge. The goal is not
exhaustive documentation, it's to capture the **why** behind choices
that a future reader (future me, a reviewer, a hiring manager) would
otherwise have to reverse-engineer from code.

## Format

Each ADR is a short markdown file named
`ADR-NNN-kebab-case-topic.md` with three sections:

- **Context** — the situation and forces at play when the decision was
  made
- **Decision** — what we picked, stated plainly
- **Consequences** — what becomes easier, harder, or constrained as
  a result

ADRs are immutable once merged. If a decision is reversed, write a new
ADR that supersedes it and note the supersession in both files.

## Phase 1 ADRs

- [ADR-001: App factory + blueprint-per-resource layout](./ADR-001-app-factory-and-blueprints.md)
- [ADR-002: Pydantic v2 over Marshmallow / flask-smorest](./ADR-002-pydantic-v2.md)
- [ADR-003: In-memory repository abstraction behind a Protocol](./ADR-003-repository-protocol.md)
- [ADR-004: Correlation ID propagation via flask.g + stdlib logging](./ADR-004-correlation-id-and-logging.md)
- [ADR-005: Stable slug IDs for jobs](./ADR-005-stable-slug-job-ids.md)
- [ADR-006: Streamlit UI kept via root-level shims during Phase 1](./ADR-006-streamlit-shims.md)

## Phase 2 ADRs

- [ADR-007: Dual-backend repositories (memory + SQLAlchemy)](./ADR-007-dual-backend-repositories.md)
- [ADR-008: Alembic workflow + env.py design](./ADR-008-alembic-workflow.md)
- [ADR-009: Session-per-request via before_request / teardown_request](./ADR-009-session-per-request.md)
- [ADR-010: JSONB portability via SQLAlchemy variants](./ADR-010-jsonb-portability.md)
- [ADR-011: Only jobs migrated to DB in Phase 2 (catalog-vs-DB boundary)](./ADR-011-catalog-vs-db-boundary.md)
