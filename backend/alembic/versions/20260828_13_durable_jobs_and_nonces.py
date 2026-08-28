"""Add delegation nonce receipts and durable background jobs.

Revision ID: 20260828_13
Revises: 20260828_12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260828_13"
down_revision: str | None = "20260828_12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "delegation_nonce_receipts",
        sa.Column("nonce", sa.String(255), primary_key=True),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False),
        sa.Column("parent_run_id", sa.String(255), nullable=False),
        sa.Column("child_run_id", sa.String(255), nullable=False),
        sa.Column("signature_hash", sa.String(64), nullable=False),
        sa.Column("issued_at", sa.BigInteger(), nullable=False),
        sa.Column("received_at", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("key_version BETWEEN 1 AND 255", name="ck_delegation_key_version"),
    )
    op.create_index(
        "ix_delegation_receipts_scope",
        "delegation_nonce_receipts",
        ["owner_id", "project_id", "received_at"],
    )
    op.create_index(
        "ix_delegation_receipts_issued_at",
        "delegation_nonce_receipts",
        ["issued_at"],
    )
    op.create_table(
        "background_jobs",
        sa.Column("job_id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("lease_generation", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("worker_id", sa.String(255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','running','succeeded','failed','dead_letter','cancelled')",
            name="ck_background_jobs_status",
        ),
        sa.CheckConstraint("kind IN ('echo','run_export')", name="ck_background_jobs_kind"),
        sa.CheckConstraint(
            "attempts >= 0 AND max_attempts BETWEEN 1 AND 10 AND attempts <= max_attempts",
            name="ck_background_jobs_attempts",
        ),
        sa.CheckConstraint("lease_generation >= 0", name="ck_background_jobs_lease_generation"),
        sa.CheckConstraint(
            "(status = 'running' AND worker_id IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (status != 'running' AND worker_id IS NULL AND lease_expires_at IS NULL)",
            name="ck_background_jobs_lease_state",
        ),
        sa.CheckConstraint(
            "(status IN ('succeeded','failed','dead_letter','cancelled') "
            "AND completed_at IS NOT NULL) OR "
            "(status IN ('pending','running') AND completed_at IS NULL)",
            name="ck_background_jobs_completion_state",
        ),
        sa.UniqueConstraint("owner_id", "project_id", "idempotency_key", name="uq_job_idempotency"),
    )
    op.create_index("ix_jobs_claim", "background_jobs", ["status", "available_at", "created_at"])
    op.create_index(
        "ix_jobs_owner_project", "background_jobs", ["owner_id", "project_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("background_jobs")
    op.drop_table("delegation_nonce_receipts")
