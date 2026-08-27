"""Add metadata-only effective-context snapshots.

Revision ID: 20260827_10
Revises: 20260827_09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260827_10"
down_revision: str | None = "20260827_09"
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

    op.create_table(
        "context_snapshots",
        sa.Column("snapshot_id", sa.String(36), primary_key=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("conversation_id", sa.String(255), nullable=False),
        sa.Column("selected_message_ids_json", sa.Text(), nullable=False),
        sa.Column("summarized_message_ids_json", sa.Text(), nullable=False),
        sa.Column("memory_ids_json", sa.Text(), nullable=False),
        sa.Column("skill_ids_json", sa.Text(), nullable=False),
        sa.Column("input_asset_hashes_json", sa.Text(), nullable=False),
        sa.Column("summary_version", sa.String(64), nullable=True),
        sa.Column("estimated_tokens", sa.BigInteger(), nullable=False),
        sa.Column("truncation_reason", sa.String(64), nullable=True),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("schema_version = 1", name="ck_context_snapshots_schema_version"),
        sa.CheckConstraint("estimated_tokens >= 0", name="ck_context_snapshots_tokens_nonnegative"),
        sa.UniqueConstraint("run_id", name="uq_context_snapshots_run"),
    )
    op.create_index("ix_context_snapshots_owner_run", "context_snapshots", ["owner_id", "run_id"])
    op.create_index(
        "ix_context_snapshots_owner_project_created",
        "context_snapshots",
        ["owner_id", "project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_context_snapshots_owner_project_created", table_name="context_snapshots")
    op.drop_index("ix_context_snapshots_owner_run", table_name="context_snapshots")
    op.drop_table("context_snapshots")
    with op.batch_alter_table("memory_facts") as batch:
        batch.drop_constraint("ck_memory_facts_key_version", type_="check")
    op.drop_table("memory_key_state")
