"""Durable privacy-safe run checkpoints and fork ancestry.

Revision ID: 20260826_04
Revises: 20260826_03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260826_04"
down_revision: str | None = "20260826_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "run_checkpoints",
        sa.Column("checkpoint_id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False),
        sa.Column(
            "source_run_id",
            sa.String(36),
            sa.ForeignKey("runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_sequence", sa.Integer(), nullable=False),
        sa.Column("conversation_snapshot", sa.Text(), nullable=False),
        sa.Column("policy_profile", sa.String(100), nullable=False),
        sa.Column("selected_memory_ids", sa.Text(), nullable=False),
        sa.Column("workspace_restoration", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "source_run_id", "source_sequence", name="uq_checkpoint_source"
        ),
        sa.CheckConstraint("workspace_restoration = 'none'", name="ck_checkpoint_no_workspace"),
    )
    op.create_index("ix_checkpoints_owner_project", "run_checkpoints", ["user_id", "project_id"])
    op.create_table(
        "fork_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "checkpoint_id",
            sa.String(36),
            sa.ForeignKey("run_checkpoints.checkpoint_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False),
        sa.Column("source_run_id", sa.String(36), nullable=False),
        sa.Column("source_sequence", sa.Integer(), nullable=False),
        sa.Column("target_conversation_id", sa.String(36), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_fork_drafts_owner_target", "fork_drafts", ["user_id", "target_conversation_id"]
    )


def downgrade() -> None:
    op.drop_table("fork_drafts")
    op.drop_table("run_checkpoints")
