# ruff: noqa: E501
"""Capability preferences and governed skill review transitions.

Revision ID: 20260901_16
Revises: 20260901_15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260901_16"
down_revision: str | None = "20260901_15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_capability_preferences",
        sa.Column("owner_id", sa.String(255), primary_key=True),
        sa.Column("project_id", sa.String(255), primary_key=True),
        sa.Column("capability_id", sa.String(128), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id", "project_id"],
            ["project_workspaces.owner_id", "project_workspaces.project_id"],
            ondelete="CASCADE",
            name="fk_capability_preference_workspace",
        ),
    )
    op.create_index(
        "ix_capability_preferences_scope",
        "project_capability_preferences",
        ["owner_id", "project_id"],
    )
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_skill_revisions_update")
        op.execute(
            "CREATE TRIGGER trg_skill_revisions_content_update BEFORE UPDATE OF package_id,owner_id,revision_number,declared_version,description,content,content_hash,manifest_hash,tags_json,references_json,source_url,source_revision,trust_state,created_at ON skill_revisions BEGIN SELECT RAISE(ABORT, 'immutable revision'); END"
        )
    elif dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_skill_revisions_immutable ON skill_revisions")
        op.execute(
            "CREATE TRIGGER trg_skill_revisions_immutable BEFORE UPDATE OF package_id,owner_id,revision_number,declared_version,description,content,content_hash,manifest_hash,tags_json,references_json,source_url,source_revision,trust_state,created_at OR DELETE ON skill_revisions FOR EACH ROW EXECUTE FUNCTION archon_spi_reject_revision_mutation()"
        )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_skill_revisions_content_update")
        op.execute(
            "CREATE TRIGGER trg_skill_revisions_update BEFORE UPDATE ON skill_revisions BEGIN SELECT RAISE(ABORT, 'immutable revision'); END"
        )
    elif dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_skill_revisions_immutable ON skill_revisions")
        op.execute(
            "CREATE TRIGGER trg_skill_revisions_immutable BEFORE UPDATE OR DELETE ON skill_revisions FOR EACH ROW EXECUTE FUNCTION archon_spi_reject_revision_mutation()"
        )
    op.drop_table("project_capability_preferences")
