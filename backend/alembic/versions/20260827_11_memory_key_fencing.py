"""Add online memory-key fencing and private context asset fingerprints.

Revision ID: 20260827_11
Revises: 20260827_10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_11"
down_revision: str | None = "20260827_10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_key_state",
        sa.Column("singleton_id", sa.String(16), primary_key=True),
        sa.Column("active_version", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "active_version BETWEEN 1 AND 255", name="ck_memory_key_state_active"
        ),
        sa.CheckConstraint("generation >= 1", name="ck_memory_key_state_generation"),
    )
    with op.batch_alter_table("memory_facts") as batch:
        batch.create_check_constraint(
            "ck_memory_facts_key_version", "key_version BETWEEN 1 AND 255"
        )
    with op.batch_alter_table("context_snapshots") as batch:
        batch.add_column(
            sa.Column(
                "input_asset_fingerprints_json",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("context_snapshots") as batch:
        batch.drop_column("input_asset_fingerprints_json")
    with op.batch_alter_table("memory_facts") as batch:
        batch.drop_constraint("ck_memory_facts_key_version", type_="check")
    op.drop_table("memory_key_state")
