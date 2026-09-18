"""Require normalized user email and enforce a sole administrator.

Revision ID: 20260918_25
Revises: 20260917_24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260918_25"
down_revision: str | None = "20260917_24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "email",
            existing_type=sa.String(length=320),
            nullable=True,
            server_default=None,
        )
    op.execute("UPDATE users SET email = NULL WHERE trim(email) = ''")
    op.execute("UPDATE users SET email = lower(trim(email)) WHERE email IS NOT NULL")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_normalized "
        "ON users (lower(email)) WHERE email IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_single_admin "
        "ON users (is_admin) WHERE is_admin = 1"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_users_single_admin")
    op.execute("DROP INDEX IF EXISTS uq_users_email_normalized")
    op.execute("UPDATE users SET email = '' WHERE email IS NULL")
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "email",
            existing_type=sa.String(length=320),
            nullable=False,
            server_default="",
        )
