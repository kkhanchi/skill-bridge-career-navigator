"""refresh_tokens table

Creates the ``refresh_tokens`` table that Phase 3 uses for the
rotation-on-refresh flow. One row per issued refresh-token grant,
keyed by ``jti`` (the JWT's unique id claim — we never store the
token string itself).

Revision ID: 0003_refresh_tokens
Revises: 0002_users_not_null_fk
Create Date: 2026-04-30 15:45:00+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0003_refresh_tokens"
down_revision: Union[str, Sequence[str], None] = "0002_users_not_null_fk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create refresh_tokens + its user_id index.

    The UNIQUE on ``jti`` is emitted as a constraint via the column
    declaration, so we don't need a separate ``create_unique_constraint``
    call. Column-level unique constraints show up in
    ``inspect(engine).get_unique_constraints("refresh_tokens")``.
    """
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("jti", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("jti"),
    )
    op.create_index(
        "ix_refresh_tokens_user_id",
        "refresh_tokens",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the index first, then the table."""
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
