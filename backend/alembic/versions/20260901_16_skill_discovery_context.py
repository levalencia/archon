"""Add governed skill discovery metadata and context provenance.

Revision ID: 20260901_16
Revises: 20260901_15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260901_16"
down_revision: str | None = "20260901_15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("skill_revisions") as batch:
        batch.add_column(sa.Column("triggers_json", sa.Text(), nullable=False, server_default="[]"))
        batch.add_column(
            sa.Column("negative_triggers_json", sa.Text(), nullable=False, server_default="[]")
        )
        batch.add_column(
            sa.Column(
                "required_capability_ids_json", sa.Text(), nullable=False, server_default="[]"
            )
        )
        batch.add_column(
            sa.Column("context_cost", sa.Integer(), nullable=False, server_default="0")
        )
    op.create_table(
        "skill_references",
        sa.Column(
            "revision_id",
            sa.String(36),
            sa.ForeignKey("skill_revisions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("path", sa.String(1024), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "byte_count >= 0 AND byte_count <= 65536", name="ck_skill_reference_bytes"
        ),
    )
    op.create_table(
        "project_skill_pins",
        sa.Column("owner_id", sa.String(255), primary_key=True),
        sa.Column("project_id", sa.String(255), primary_key=True),
        sa.Column(
            "revision_id", sa.String(36), sa.ForeignKey("skill_revisions.id"), primary_key=True
        ),
        sa.Column("revision_owner_id", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id", "project_id"],
            ["project_workspaces.owner_id", "project_workspaces.project_id"],
            ondelete="CASCADE",
            name="fk_skill_pin_workspace",
        ),
    )
    op.create_index(
        "ix_skill_pins_scope_enabled",
        "project_skill_pins",
        ["owner_id", "project_id", "enabled"],
    )
    with op.batch_alter_table("context_snapshots") as batch:
        batch.add_column(
            sa.Column("instruction_revisions_json", sa.Text(), nullable=False, server_default="[]")
        )
        batch.add_column(
            sa.Column("skill_revisions_json", sa.Text(), nullable=False, server_default="[]")
        )
        batch.add_column(
            sa.Column(
                "selected_capability_ids_json", sa.Text(), nullable=False, server_default="[]"
            )
        )
        batch.add_column(
            sa.Column(
                "rejected_capability_ids_json", sa.Text(), nullable=False, server_default="[]"
            )
        )
        batch.add_column(
            sa.Column("context_cost_bytes", sa.BigInteger(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("context_snapshots") as batch:
        batch.drop_column("context_cost_bytes")
        batch.drop_column("rejected_capability_ids_json")
        batch.drop_column("selected_capability_ids_json")
        batch.drop_column("skill_revisions_json")
        batch.drop_column("instruction_revisions_json")
    op.drop_index("ix_skill_pins_scope_enabled", table_name="project_skill_pins")
    op.drop_table("project_skill_pins")
    op.drop_table("skill_references")
    with op.batch_alter_table("skill_revisions") as batch:
        batch.drop_column("context_cost")
        batch.drop_column("required_capability_ids_json")
        batch.drop_column("negative_triggers_json")
        batch.drop_column("triggers_json")
