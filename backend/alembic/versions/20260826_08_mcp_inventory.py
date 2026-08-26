"""Add owner-scoped MCP server configuration and discovered inventory.

Revision ID: 20260826_08
Revises: 20260826_07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260826_08"
down_revision: str | None = "20260826_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("profile_id", sa.String(255), nullable=False),
        sa.Column("transport", sa.String(16), nullable=False, server_default="stdio"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("health", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("transport = 'stdio'", name="ck_mcp_servers_transport"),
        sa.CheckConstraint(
            "health IN ('unknown','healthy','error','disabled')", name="ck_mcp_servers_health"
        ),
        sa.UniqueConstraint("owner_id", "project_id", "name", name="uq_mcp_server_scope_name"),
    )
    op.create_index("ix_mcp_servers_scope", "mcp_servers", ["owner_id", "project_id"])
    op.create_table(
        "mcp_tools",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "server_id",
            sa.String(36),
            sa.ForeignKey("mcp_servers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("description", sa.String(10000), nullable=True),
        sa.Column("input_schema_json", sa.Text(), nullable=False),
        sa.Column("read_only", sa.Boolean(), nullable=False),
        sa.Column("destructive", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("version", sa.String(100), nullable=True),
        sa.UniqueConstraint("server_id", "name", name="uq_mcp_tool_server_name"),
    )
    op.create_index("ix_mcp_tools_server", "mcp_tools", ["server_id"])


def downgrade() -> None:
    op.drop_index("ix_mcp_tools_server", table_name="mcp_tools")
    op.drop_table("mcp_tools")
    op.drop_index("ix_mcp_servers_scope", table_name="mcp_servers")
    op.drop_table("mcp_servers")
