"""users.user_id NOT NULL + CASCADE on profiles and analyses

Flips the previously-nullable ``profiles.user_id`` and
``analyses.user_id`` columns to NOT NULL, and changes their FK
``ondelete`` from ``SET NULL`` to ``CASCADE``. A Phase 3
authenticated system has no meaningful "orphan" rows — every
profile and every analysis is owned by exactly one user, and if
that user is deleted the owned rows go with them.

Revision ID: 0002_users_not_null_fk
Revises: 0001_initial_schema
Create Date: 2026-04-30 15:30:00+00:00

DESTRUCTIVE STEP WARNING
------------------------

``upgrade()`` begins by DELETE-ing every row in ``profiles`` and
``analyses`` whose ``user_id IS NULL``. Roadmaps referencing those
analyses are removed by the Phase 2 ``ON DELETE CASCADE`` on
``roadmaps.analysis_id``.

In Phase 3 development the only data in these tables is synthetic
test payload, so the DELETE is acceptable. Production environments
that carry real orphan rows MUST backfill them before running this
migration — typical runbook:

  1. Insert a placeholder ``placeholder@local`` user.
  2. ``UPDATE profiles SET user_id = <placeholder_id> WHERE user_id IS NULL;``
  3. Same for analyses.
  4. Alembic upgrade head (the DELETE now finds zero rows).

``downgrade()`` reverses the schema shape (nullability + ondelete)
but does NOT restore the deleted rows. That is a one-way data loss.

SQLite / batch mode
-------------------

SQLite cannot ``ALTER COLUMN NOT NULL`` or swap an FK ``ondelete`` in
place. Alembic's ``batch_alter_table`` rewrites the table under the
hood (copy into a temp table with the new schema, drop old, rename).
The old FK in 0001 is anonymous, so instead of drop_constraint by
name we use ``copy_from`` to hand batch mode a fully-specified
target table — batch then derives the delta (nullability flip,
FK ondelete swap) and produces the right SQL for both dialects.
On Postgres the same code emits plain ``ALTER`` statements.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0002_users_not_null_fk"
down_revision: Union[str, Sequence[str], None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Named FK constraints to attach in this migration's target shape.
# These names didn't exist in 0001 (FKs there are anonymous), so we
# apply them here as part of the batch-rewrite and reference them by
# name in ``downgrade``.
_PROFILES_FK_USER = "fk_profiles_user_id"
_ANALYSES_FK_USER = "fk_analyses_user_id"


def _build_profiles_target(metadata: sa.MetaData) -> sa.Table:
    """The target shape of ``profiles`` after this migration runs.

    Used as ``copy_from`` for batch_alter_table so SQLite's table
    rewrite produces exactly this schema — nullability flipped,
    user_id FK set to CASCADE.
    """
    return sa.Table(
        "profiles",
        metadata,
        sa.Column("id", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False, index=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("skills", sa.JSON(), nullable=False),
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
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name=_PROFILES_FK_USER,
        ),
    )


def _build_analyses_target(metadata: sa.MetaData) -> sa.Table:
    """The target shape of ``analyses`` after this migration runs."""
    return sa.Table(
        "analyses",
        metadata,
        sa.Column("id", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("profile_id", sa.String(length=32), nullable=True, index=True),
        sa.Column("job_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name=_ANALYSES_FK_USER,
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profiles.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            ondelete="RESTRICT",
        ),
    )


def _build_profiles_original(metadata: sa.MetaData) -> sa.Table:
    """The 0001 shape of ``profiles`` (user_id nullable, ondelete=SET NULL).

    Used as ``copy_from`` on downgrade to reverse the shape change.
    """
    return sa.Table(
        "profiles",
        metadata,
        sa.Column("id", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=True, index=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("skills", sa.JSON(), nullable=False),
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
            ["user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
    )


def _build_analyses_original(metadata: sa.MetaData) -> sa.Table:
    return sa.Table(
        "analyses",
        metadata,
        sa.Column("id", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=True),
        sa.Column("profile_id", sa.String(length=32), nullable=True, index=True),
        sa.Column("job_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profiles.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            ondelete="RESTRICT",
        ),
    )


def upgrade() -> None:
    """Purge orphan rows, then flip nullability + FK cascade.

    SQLite's batch_alter_table rewrites the table, which drops the
    pre-existing ``ix_profiles_user_id`` index in the process. We
    recreate it after each batch so the post-migration schema
    matches the 0001 index set plus the new nullability/FK shape.
    """

    # 1. Data step.
    op.execute("DELETE FROM analyses WHERE user_id IS NULL")
    op.execute("DELETE FROM profiles WHERE user_id IS NULL")

    # 2. profiles: rewrite, then recreate the dropped index.
    target_metadata = sa.MetaData()
    with op.batch_alter_table(
        "profiles", copy_from=_build_profiles_target(target_metadata)
    ) as batch:
        batch.alter_column(
            "user_id",
            existing_type=sa.String(length=32),
            nullable=False,
        )
    op.create_index("ix_profiles_user_id", "profiles", ["user_id"], unique=False)

    # 3. analyses: rewrite, then recreate the two dropped indexes.
    target_metadata = sa.MetaData()
    with op.batch_alter_table(
        "analyses", copy_from=_build_analyses_target(target_metadata)
    ) as batch:
        batch.alter_column(
            "user_id",
            existing_type=sa.String(length=32),
            nullable=False,
        )
    op.create_index(
        "ix_analyses_profile_id", "analyses", ["profile_id"], unique=False
    )
    op.create_index("ix_analyses_job_id", "analyses", ["job_id"], unique=False)


def downgrade() -> None:
    """Reverse schema changes only. Deleted rows are NOT restored."""

    # Drop the Phase 3 indexes before the batch rewrite so they don't
    # collide with the recreations below.
    op.drop_index("ix_analyses_job_id", table_name="analyses")
    op.drop_index("ix_analyses_profile_id", table_name="analyses")

    original_metadata = sa.MetaData()
    with op.batch_alter_table(
        "analyses", copy_from=_build_analyses_original(original_metadata)
    ) as batch:
        batch.alter_column(
            "user_id",
            existing_type=sa.String(length=32),
            nullable=True,
        )
    op.create_index(
        "ix_analyses_profile_id", "analyses", ["profile_id"], unique=False
    )
    op.create_index("ix_analyses_job_id", "analyses", ["job_id"], unique=False)

    op.drop_index("ix_profiles_user_id", table_name="profiles")

    original_metadata = sa.MetaData()
    with op.batch_alter_table(
        "profiles", copy_from=_build_profiles_original(original_metadata)
    ) as batch:
        batch.alter_column(
            "user_id",
            existing_type=sa.String(length=32),
            nullable=True,
        )
    op.create_index("ix_profiles_user_id", "profiles", ["user_id"], unique=False)

