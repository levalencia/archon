"""Add durable effect ledger and monetary reservation schema.

Revision ID: 20260827_09
Revises: 20260826_08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260827_09"
down_revision: str | None = "20260826_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Batch mode rebuilds runs on SQLite and emits valid ALTER TABLE DDL on PostgreSQL.
    # Server defaults make all pre-existing rows satisfy the new invariant.
    with op.batch_alter_table("runs") as batch:
        batch.add_column(
            sa.Column("budget_limit_nusd", sa.BigInteger(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("budget_spent_nusd", sa.BigInteger(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("budget_reserved_nusd", sa.BigInteger(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("budget_opened_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_check_constraint(
            "ck_runs_budget_amounts_nonnegative",
            "budget_limit_nusd >= 0 AND budget_spent_nusd >= 0 AND budget_reserved_nusd >= 0",
        )
        batch.create_check_constraint(
            "ck_runs_budget_within_limit",
            "budget_spent_nusd + budget_reserved_nusd <= budget_limit_nusd",
        )

    op.create_table(
        "project_budgets",
        sa.Column("owner_id", sa.String(255), primary_key=True),
        sa.Column("project_id", sa.String(255), primary_key=True),
        sa.Column("limit_nusd", sa.BigInteger(), nullable=False),
        sa.Column("spent_nusd", sa.BigInteger(), nullable=False),
        sa.Column("reserved_nusd", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "limit_nusd >= 0 AND spent_nusd >= 0 AND reserved_nusd >= 0",
            name="ck_project_budgets_amounts_nonnegative",
        ),
        sa.CheckConstraint(
            "spent_nusd + reserved_nusd <= limit_nusd",
            name="ck_project_budgets_within_limit",
        ),
    )

    op.create_table(
        "effects",
        sa.Column("effect_id", sa.String(255), primary_key=True),
        sa.Column("identity_version", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("tool_name", sa.String(255), nullable=False),
        sa.Column("schema_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("output_hash", sa.String(64), nullable=True),
        sa.Column("output_size", sa.BigInteger(), nullable=True),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("review_disposition", sa.String(32), nullable=True),
        sa.Column("reviewed_by", sa.String(255), nullable=True),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('reserved','committed','failed','indeterminate')",
            name="ck_effects_state",
        ),
        sa.CheckConstraint("identity_version >= 0", name="ck_effects_identity_version_nonnegative"),
        sa.CheckConstraint(
            "output_size IS NULL OR output_size >= 0", name="ck_effects_output_size_nonnegative"
        ),
    )
    op.create_index(
        "ix_effects_owner_project_state", "effects", ["owner_id", "project_id", "state"]
    )
    op.create_index("ix_effects_owner_run", "effects", ["owner_id", "run_id"])
    op.create_index("ix_effects_run_state", "effects", ["run_id", "state"])

    op.create_table(
        "model_charges",
        sa.Column("charge_id", sa.String(128), primary_key=True),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("reserved_nusd", sa.BigInteger(), nullable=False),
        sa.Column("actual_nusd", sa.BigInteger(), nullable=True),
        sa.Column("provider", sa.String(100), nullable=True),
        sa.Column("model", sa.String(255), nullable=True),
        sa.Column("input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("output_tokens", sa.BigInteger(), nullable=True),
        sa.Column("cache_read_tokens", sa.BigInteger(), nullable=True),
        sa.Column("cache_write_tokens", sa.BigInteger(), nullable=True),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('reserved','dispatched','reconciled','released','indeterminate')",
            name="ck_model_charges_state",
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_model_charges_ordinal_nonnegative"),
        sa.CheckConstraint("reserved_nusd >= 0", name="ck_model_charges_reserved_nonnegative"),
        sa.CheckConstraint(
            "actual_nusd IS NULL OR actual_nusd >= 0",
            name="ck_model_charges_actual_nonnegative",
        ),
        sa.CheckConstraint(
            "(input_tokens IS NULL OR input_tokens >= 0) AND "
            "(output_tokens IS NULL OR output_tokens >= 0) AND "
            "(cache_read_tokens IS NULL OR cache_read_tokens >= 0) AND "
            "(cache_write_tokens IS NULL OR cache_write_tokens >= 0)",
            name="ck_model_charges_tokens_nonnegative",
        ),
        sa.UniqueConstraint("run_id", "ordinal", name="uq_model_charges_run_ordinal"),
    )
    op.create_index(
        "ix_model_charges_owner_project_state",
        "model_charges",
        ["owner_id", "project_id", "state"],
    )
    op.create_index("ix_model_charges_run_state", "model_charges", ["run_id", "state"])


def downgrade() -> None:
    op.drop_index("ix_model_charges_run_state", table_name="model_charges")
    op.drop_index("ix_model_charges_owner_project_state", table_name="model_charges")
    op.drop_table("model_charges")

    op.drop_index("ix_effects_run_state", table_name="effects")
    op.drop_index("ix_effects_owner_run", table_name="effects")
    op.drop_index("ix_effects_owner_project_state", table_name="effects")
    op.drop_table("effects")
    op.drop_table("project_budgets")

    with op.batch_alter_table("runs") as batch:
        batch.drop_constraint("ck_runs_budget_within_limit", type_="check")
        batch.drop_constraint("ck_runs_budget_amounts_nonnegative", type_="check")
        batch.drop_column("budget_reserved_nusd")
        batch.drop_column("budget_spent_nusd")
        batch.drop_column("budget_limit_nusd")
        batch.drop_column("budget_opened_at")
