"""Durable exact project instruction snapshots and scoped current pointer.

Revision ID: 20260901_18
Revises: 20260901_17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260901_18"
down_revision: str | None = "20260901_17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_revision_guard(*, strict: bool) -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_project_instruction_revisions_update")
        op.execute("DROP TRIGGER IF EXISTS trg_project_instruction_revisions_content_update")
        columns = (
            "id,owner_id,project_id,revision_number,content,content_hash,created_at"
            if not strict
            else (
                "id,owner_id,project_id,revision_number,content,content_hash,"
                "review_state,created_at"
            )
        )
        name = (
            "trg_project_instruction_revisions_content_update"
            if not strict
            else "trg_project_instruction_revisions_update"
        )
        op.execute(
            f"CREATE TRIGGER {name} BEFORE UPDATE OF {columns} ON project_instruction_revisions "
            "BEGIN SELECT RAISE(ABORT, 'immutable revision'); END"
        )
    elif dialect == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_project_instruction_revisions_immutable "
            "ON project_instruction_revisions"
        )
        columns = (
            "id,owner_id,project_id,revision_number,content,content_hash,created_at"
            if not strict
            else (
                "id,owner_id,project_id,revision_number,content,content_hash,"
                "review_state,created_at"
            )
        )
        op.execute(
            "CREATE TRIGGER trg_project_instruction_revisions_immutable "
            f"BEFORE UPDATE OF {columns} "
            "OR DELETE ON project_instruction_revisions FOR EACH ROW "
            "EXECUTE FUNCTION archon_spi_reject_revision_mutation()"
        )


def upgrade() -> None:
    op.create_table(
        "project_instruction_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("revision_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("relative_path", sa.String(1024), nullable=False),
        sa.Column("scope_path", sa.String(1024), nullable=False),
        sa.Column("family", sa.String(16), nullable=False),
        sa.Column("is_override", sa.Boolean(), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["revision_id", "owner_id", "project_id"],
            [
                "project_instruction_revisions.id",
                "project_instruction_revisions.owner_id",
                "project_instruction_revisions.project_id",
            ],
            ondelete="CASCADE",
            name="fk_instruction_source_revision_scope",
        ),
        sa.UniqueConstraint("revision_id", "ordinal", name="uq_instruction_source_order"),
        sa.CheckConstraint("ordinal >= 0", name="ck_instruction_source_ordinal"),
        sa.CheckConstraint(
            "byte_count >= 0 AND byte_count <= 262144", name="ck_instruction_source_bytes"
        ),
        sa.CheckConstraint(
            "family IN ('archon','agents','claude','manual')",
            name="ck_instruction_source_family",
        ),
    )
    op.create_index(
        "ix_instruction_sources_revision_order",
        "project_instruction_sources",
        ["revision_id", "ordinal"],
    )
    # Preserve every pre-snapshot revision as one exact manual source.
    op.execute(
        "INSERT INTO project_instruction_sources "
        "(id,revision_id,owner_id,project_id,ordinal,relative_path,scope_path,family,"
        "is_override,byte_count,content_hash,content) "
        "SELECT id,id,owner_id,project_id,0,'.archon/instructions.md','.',"
        "'manual',0,length(CAST(content AS BLOB)),content_hash,content "
        "FROM project_instruction_revisions"
        if op.get_bind().dialect.name == "sqlite"
        else "INSERT INTO project_instruction_sources "
        "(id,revision_id,owner_id,project_id,ordinal,relative_path,scope_path,family,"
        "is_override,byte_count,content_hash,content) "
        "SELECT id,id,owner_id,project_id,0,'.archon/instructions.md','.',"
        "'manual',false,octet_length(content),content_hash,content "
        "FROM project_instruction_revisions"
    )
    _replace_revision_guard(strict=False)
    # A legacy current pointer represented approval, despite the old API only faking that state.
    op.execute(
        "UPDATE project_instruction_revisions SET review_state='approved' "
        "WHERE EXISTS (SELECT 1 FROM project_workspaces AS workspace "
        "WHERE workspace.current_instruction_revision_id=project_instruction_revisions.id "
        "AND workspace.owner_id=project_instruction_revisions.owner_id "
        "AND workspace.project_id=project_instruction_revisions.project_id)"
    )
    # Fail closed on any pointer written before database-level scope fencing existed.
    op.execute(
        "UPDATE project_workspaces SET current_instruction_revision_id=NULL "
        "WHERE current_instruction_revision_id IS NOT NULL AND NOT EXISTS "
        "(SELECT 1 FROM project_instruction_revisions AS revision "
        "WHERE revision.id=project_workspaces.current_instruction_revision_id "
        "AND revision.owner_id=project_workspaces.owner_id "
        "AND revision.project_id=project_workspaces.project_id)"
    )
    with op.batch_alter_table("project_workspaces") as batch:
        batch.create_foreign_key(
            "fk_project_workspace_current_instruction_scope",
            "project_instruction_revisions",
            ["current_instruction_revision_id", "owner_id", "project_id"],
            ["id", "owner_id", "project_id"],
        )
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER trg_project_instruction_sources_{operation.lower()} "
                f"BEFORE {operation} ON project_instruction_sources "
                "BEGIN SELECT RAISE(ABORT, 'immutable instruction source'); END"
            )
    elif dialect == "postgresql":
        op.execute(
            "CREATE TRIGGER trg_project_instruction_sources_immutable BEFORE UPDATE OR DELETE "
            "ON project_instruction_sources FOR EACH ROW "
            "EXECUTE FUNCTION archon_spi_reject_revision_mutation()"
        )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    boolean_false = "0" if dialect == "sqlite" else "false"
    unrepresentable = op.get_bind().execute(
        sa.text(
            "SELECT 1 FROM project_instruction_revisions AS revision WHERE "
            "(SELECT count(*) FROM project_instruction_sources AS source "
            "WHERE source.revision_id=revision.id) != 1 OR NOT EXISTS "
            "(SELECT 1 FROM project_instruction_sources AS source WHERE "
            "source.revision_id=revision.id AND source.id=revision.id AND source.ordinal=0 "
            "AND source.relative_path='.archon/instructions.md' AND source.scope_path='.' "
            "AND source.family='manual' AND source.is_override="
            f"{boolean_false} AND source.content=revision.content) LIMIT 1"
        )
    ).first()
    if unrepresentable is not None:
        raise RuntimeError("cannot downgrade: exact instruction snapshot is not representable")
    if dialect == "sqlite":
        for operation in ("update", "delete"):
            op.execute(f"DROP TRIGGER IF EXISTS trg_project_instruction_sources_{operation}")
    elif dialect == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_project_instruction_sources_immutable "
            "ON project_instruction_sources"
        )
    _replace_revision_guard(strict=True)
    with op.batch_alter_table("project_workspaces") as batch:
        batch.drop_constraint("fk_project_workspace_current_instruction_scope", type_="foreignkey")
    op.drop_table("project_instruction_sources")
