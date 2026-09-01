"""Persist deployment-profile transport kind for MCP servers.

Revision ID: 20260901_19
Revises: 20260901_18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260901_19"
down_revision: str | None = "20260901_18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("mcp_servers") as batch:
        batch.drop_constraint("ck_mcp_servers_transport", type_="check")
        batch.create_check_constraint(
            "ck_mcp_servers_transport", "transport IN ('stdio','streamable_http')"
        )
        batch.alter_column(
            "enabled", existing_type=sa.Boolean(), nullable=False, server_default=sa.false()
        )


def downgrade() -> None:
    # Never silently reinterpret a remote server as a local stdio process.
    if op.get_bind().execute(
        sa.text("SELECT 1 FROM mcp_servers WHERE transport = 'streamable_http' LIMIT 1")
    ).first() is not None:
        raise RuntimeError("cannot downgrade: streamable_http MCP servers are not representable")
    with op.batch_alter_table("mcp_servers") as batch:
        batch.drop_constraint("ck_mcp_servers_transport", type_="check")
        batch.create_check_constraint("ck_mcp_servers_transport", "transport = 'stdio'")
        batch.alter_column(
            "enabled", existing_type=sa.Boolean(), nullable=False, server_default=sa.true()
        )
