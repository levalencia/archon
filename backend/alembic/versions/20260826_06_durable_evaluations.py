"""Persist owner-scoped evaluations of recorded runs.

Revision ID: 20260826_06
Revises: 20260826_05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260826_06"
down_revision: str | None = "20260826_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False),
        sa.Column("dataset_id", sa.String(255), nullable=False),
        sa.Column("dataset_version", sa.String(100), nullable=False),
        sa.Column("dataset_hash", sa.String(64), nullable=False),
        sa.Column("source_run_ids_json", sa.JSON(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("passed", sa.Integer(), nullable=True),
        sa.Column("aggregate_metrics_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running','completed','failed')", name="ck_eval_runs_status"
        ),
        sa.CheckConstraint("threshold >= 0 AND threshold <= 1", name="ck_eval_runs_threshold"),
        sa.CheckConstraint("passed IS NULL OR passed IN (0,1)", name="ck_eval_runs_passed"),
    )
    op.create_index(
        "ix_eval_runs_owner_project_created",
        "eval_runs",
        ["owner_id", "project_id", "created_at"],
    )
    op.create_table(
        "eval_case_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "eval_run_id",
            sa.String(36),
            sa.ForeignKey("eval_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_run_id", sa.String(36), nullable=False),
        sa.Column("case_key", sa.String(255), nullable=False),
        sa.Column("passed", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("checks_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("passed IN (0,1)", name="ck_eval_case_results_passed"),
        sa.CheckConstraint("score >= 0 AND score <= 1", name="ck_eval_case_results_score"),
        sa.UniqueConstraint("eval_run_id", "case_key", name="uq_eval_case_results_run_case"),
    )
    op.create_index("ix_eval_case_results_eval_run", "eval_case_results", ["eval_run_id"])


def downgrade() -> None:
    op.drop_table("eval_case_results")
    op.drop_table("eval_runs")
