"""initial schema

Creates the five Phase 2 tables (users, profiles, jobs, analyses,
roadmaps) with their indexes, foreign keys, and portable JSON columns.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-04-30 07:56:04+00:00

Hand-review notes (against autogenerate):

- Added ``from sqlalchemy import Text`` — autogenerate emitted
  ``postgresql.JSONB(astext_type=Text())`` but didn't import Text,
  which would crash the migration on Postgres.
- Renamed file from ``2026_04_30_0756-<hash>_initial_schema.py`` to
  ``0001_initial_schema.py`` to keep migration filenames short and
  orderable.
- Table creation order matches foreign-key dependencies (users ->
  profiles/analyses -> jobs -> roadmaps).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Portable JSON type used by every JSON-bearing column in this schema.
# Plain JSON on SQLite, native JSONB on Postgres.
_JSONB = sa.JSON().with_variant(
    postgresql.JSONB(astext_type=Text()),
    "postgresql",
)


def upgrade() -> None:
    """Create all Phase 2 tables + indexes."""

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("required_skills", _JSONB, nullable=False),
        sa.Column("preferred_skills", _JSONB, nullable=False),
        sa.Column("experience_level", sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_title", "jobs", ["title"], unique=False)
    op.create_index(
        "ix_jobs_experience_level", "jobs", ["experience_level"], unique=False
    )

    op.create_table(
        "profiles",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("skills", _JSONB, nullable=False),
        sa.Column("experience_years", sa.Integer(), nullable=False),
        sa.Column("education", sa.String(length=200), nullable=False),
        sa.Column("target_role", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_profiles_user_id", "profiles", ["user_id"], unique=False)

    op.create_table(
        "analyses",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=True),
        sa.Column("profile_id", sa.String(length=32), nullable=True),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("result", _JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["profiles.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_analyses_profile_id", "analyses", ["profile_id"], unique=False
    )
    op.create_index("ix_analyses_job_id", "analyses", ["job_id"], unique=False)

    op.create_table(
        "roadmaps",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("analysis_id", sa.String(length=32), nullable=False),
        sa.Column("phases", _JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"], ["analyses.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_roadmaps_analysis_id", "roadmaps", ["analysis_id"], unique=False
    )


def downgrade() -> None:
    """Drop everything in reverse dependency order."""

    op.drop_index("ix_roadmaps_analysis_id", table_name="roadmaps")
    op.drop_table("roadmaps")

    op.drop_index("ix_analyses_job_id", table_name="analyses")
    op.drop_index("ix_analyses_profile_id", table_name="analyses")
    op.drop_table("analyses")

    op.drop_index("ix_profiles_user_id", table_name="profiles")
    op.drop_table("profiles")

    op.drop_index("ix_jobs_experience_level", table_name="jobs")
    op.drop_index("ix_jobs_title", table_name="jobs")
    op.drop_table("jobs")

    op.drop_table("users")
