"""Enforce run parent lineage in the database.

Revision ID: 20260826_07
Revises: 20260826_06
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260826_07"
down_revision: str | None = "20260826_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAME = "fk_runs_parent_run_id_runs"


def upgrade() -> None:
    # batch mode recreates the table on SQLite and emits ALTER TABLE on PostgreSQL.
    # Existing NULL roots and valid parent references are copied unchanged.
    with op.batch_alter_table("runs") as batch:
        batch.create_foreign_key(_NAME, "runs", ["parent_run_id"], ["run_id"], ondelete="RESTRICT")


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.drop_constraint(_NAME, type_="foreignkey")
