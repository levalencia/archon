"""Add curated learning knowledge and tutor conversation tables.

Revision ID: 20260912_23
Revises: 20260902_22
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260912_23"
down_revision: str | None = "20260902_22"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "learning_sources",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("source_key", sa.String(length=1000), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("source_revision", sa.String(length=80), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("locator_json", sa.Text(), nullable=False),
        sa.Column("context_keys_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('documentation','code','test','video','visual')",
            name="ck_learning_sources_kind",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_key"),
    )
    op.create_index(
        "ix_learning_sources_kind_revision",
        "learning_sources",
        ["kind", "source_revision"],
        unique=False,
    )
    op.create_table(
        "learning_chunks",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=32), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("embedding_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["learning_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "chunk_index", name="uq_learning_chunk_index"),
    )
    op.create_index("ix_learning_chunks_source", "learning_chunks", ["source_id"], unique=False)
    op.create_table(
        "learning_tutor_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=255), nullable=False),
        sa.Column("project_id", sa.String(length=255), nullable=False),
        sa.Column("context_key", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id", "project_id", "context_key", name="uq_learning_tutor_context"
        ),
    )
    op.create_index(
        "ix_learning_tutor_owner_updated",
        "learning_tutor_sessions",
        ["owner_id", "updated_at"],
        unique=False,
    )
    op.create_table(
        "learning_tutor_turns",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=255), nullable=False),
        sa.Column("project_id", sa.String(length=255), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("context_json", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("diagram_json", sa.Text(), nullable=True),
        sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["learning_tutor_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_learning_tutor_turns_session_created",
        "learning_tutor_turns",
        ["session_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_learning_tutor_turns_owner_project",
        "learning_tutor_turns",
        ["owner_id", "project_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_learning_tutor_turns_owner_project", table_name="learning_tutor_turns")
    op.drop_index("ix_learning_tutor_turns_session_created", table_name="learning_tutor_turns")
    op.drop_table("learning_tutor_turns")
    op.drop_index("ix_learning_tutor_owner_updated", table_name="learning_tutor_sessions")
    op.drop_table("learning_tutor_sessions")
    op.drop_index("ix_learning_chunks_source", table_name="learning_chunks")
    op.drop_table("learning_chunks")
    op.drop_index("ix_learning_sources_kind_revision", table_name="learning_sources")
    op.drop_table("learning_sources")
