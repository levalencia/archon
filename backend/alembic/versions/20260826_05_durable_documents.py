"""Durable owner-scoped documents and honest SQL/JSON vectors.

Revision ID: 20260826_05
Revises: 20260826_04

Legacy vector chunks had no ownership boundary and are deliberately dropped. They
cannot be safely attributed to an owner; source documents must be re-ingested.
Downgrade recreates the legacy schema empty, making re-upgrade deterministic.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260826_05"
down_revision: str | None = "20260826_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "vector_chunks" in inspector.get_table_names():
        op.drop_table("vector_chunks")
    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("source", sa.String(1000), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("characters", sa.Integer(), nullable=False),
        sa.Column("chunks", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("embedding_provider", sa.String(100), nullable=False),
        sa.Column("embedding_model", sa.String(255), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('processing','ready','failed')", name="ck_documents_status"),
    )
    op.create_index(
        "ix_documents_owner_project_created", "documents", ["owner_id", "project_id", "created_at"]
    )
    op.create_table(
        "vector_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("embedding_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_vector_chunk_index"),
    )
    op.create_index(
        "ix_vector_chunks_scope_document",
        "vector_chunks",
        ["owner_id", "project_id", "document_id"],
    )


def downgrade() -> None:
    op.drop_table("vector_chunks")
    op.drop_table("documents")
    op.create_table(
        "vector_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(16), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("embedding_json", sa.Text(), nullable=True),
    )
