"""Create core tables predating the Alembic migration chain.

Revision ID: 20260826_00
Revises:

These six tables (users, api_keys, conversations, messages, audit_entries,
artifacts) were originally created by SQLAlchemy ``metadata.create_all`` during
early development and were never given an Alembic migration.  Without this
migration a fresh Postgres database cannot start.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260826_00"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False, server_default=""),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_admin", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_index("ix_users_username", "users", ["username"])

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"])
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])

    op.create_table(
        "conversations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "title",
            sa.String(length=200),
            nullable=False,
            server_default="New Conversation",
        ),
        sa.Column(
            "user_id", sa.String(length=36), nullable=False, server_default="default"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Integer(), server_default="1"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])

    op.create_table(
        "audit_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("timestamp", sa.String(length=30), nullable=False),
        sa.Column("agent_id", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource", sa.String(length=500), nullable=False),
        sa.Column("parameters", sa.Text(), nullable=True),
        sa.Column("result", sa.String(length=50), server_default="success"),
        sa.Column("security_level", sa.String(length=20), server_default="info"),
        sa.Column("correlation_id", sa.String(length=36), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_entries_correlation_id", "audit_entries", ["correlation_id"]
    )

    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("message_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("artifact_type", sa.String(length=20), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_artifacts_conversation_id", "artifacts", ["conversation_id"]
    )


def downgrade() -> None:
    op.drop_table("artifacts")
    op.drop_table("audit_entries")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("api_keys")
    op.drop_table("users")
