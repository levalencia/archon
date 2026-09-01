"""Persist provider-visible capability provenance.

Revision ID: 20260901_21
Revises: 20260901_20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260901_21"
down_revision: str | None = "20260901_20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("context_snapshots") as batch:
        batch.add_column(
            sa.Column(
                "capability_references_json",
                sa.Text(),
                nullable=False,
                server_default="[]",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("context_snapshots") as batch:
        batch.drop_column("capability_references_json")
