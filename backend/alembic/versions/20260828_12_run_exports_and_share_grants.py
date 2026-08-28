"""Add secure run exports and purpose-bound share grants.

Revision ID: 20260828_12
Revises: 20260827_11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260828_12"
down_revision: str | None = "20260827_11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "run_exports",
        sa.Column("export_id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("bundle_json", sa.Text(), nullable=False),
        sa.Column("content_checksum", sa.String(64), nullable=False),
        sa.Column("manifest_checksum", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("schema_version = 1", name="ck_run_exports_schema_version"),
        sa.UniqueConstraint("export_id", "owner_id", name="uq_run_exports_export_owner"),
        sa.UniqueConstraint(
            "owner_id", "run_id", "content_checksum", name="uq_run_exports_content"
        ),
    )
    op.create_index("ix_run_exports_owner_run", "run_exports", ["owner_id", "run_id", "created_at"])
    op.create_table(
        "run_share_grants",
        sa.Column("grant_id", sa.String(36), primary_key=True),
        sa.Column("export_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("recipient_user_id", sa.String(255), nullable=False),
        sa.Column("purpose", sa.String(120), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["export_id", "owner_id"],
            ["run_exports.export_id", "run_exports.owner_id"],
            ondelete="CASCADE",
            name="fk_share_export_owner",
        ),
        sa.CheckConstraint(
            "purpose IN ('audit','incident_review','evaluation','support')",
            name="ck_share_purpose",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_share_expiry_after_create"),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at", name="ck_share_revoked_after_create"
        ),
    )
    op.create_index(
        "ix_share_grants_owner_export", "run_share_grants", ["owner_id", "export_id", "created_at"]
    )
    op.create_index("ix_share_grants_token_hash", "run_share_grants", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_table("run_share_grants")
    op.drop_table("run_exports")
