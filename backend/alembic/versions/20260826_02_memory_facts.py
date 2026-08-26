"""Create owner/project-scoped encrypted memory facts.

Revision ID: 20260826_02
Revises: 20260826_01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260826_02"
down_revision: str | None = "20260826_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_scopes",
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("project_id", sa.String(length=255), nullable=False),
        sa.Column("chars_used", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("chars_used >= 0", name="ck_memory_scopes_chars_nonnegative"),
        sa.CheckConstraint("version >= 0", name="ck_memory_scopes_version_nonnegative"),
        sa.PrimaryKeyConstraint("user_id", "project_id"),
    )
    op.create_table(
        "memory_facts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("project_id", sa.String(length=255), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_facts_owner", "memory_facts", ["user_id"])
    op.create_index("ix_memory_facts_owner_project", "memory_facts", ["user_id", "project_id"])


def downgrade() -> None:
    op.drop_table("memory_facts")
    op.drop_table("memory_scopes")
