"""Add durable skills and project instruction revisions.

Revision ID: 20260901_15
Revises: 20260828_14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260901_15"
down_revision: str | None = "20260828_14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IMMUTABLE = ("skill_revisions", "project_instruction_revisions")


def _create_immutability_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for table in _IMMUTABLE:
            for operation in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER trg_{table}_{operation.lower()} BEFORE {operation} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'immutable revision'); END"
                )
    elif dialect == "postgresql":
        op.execute(
            "CREATE FUNCTION archon_spi_reject_revision_mutation() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'immutable revision'; END $$"
        )
        for table in _IMMUTABLE:
            op.execute(
                f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION archon_spi_reject_revision_mutation()"
            )


def _drop_immutability_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for table in _IMMUTABLE:
            for operation in ("update", "delete"):
                op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_{operation}")
    elif dialect == "postgresql":
        for table in _IMMUTABLE:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
        op.execute("DROP FUNCTION IF EXISTS archon_spi_reject_revision_mutation()")


def upgrade() -> None:
    op.create_table(
        "skill_packages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "name", name="uq_skill_packages_owner_name"),
        sa.UniqueConstraint("id", "owner_id", name="uq_skill_packages_scope"),
    )
    op.create_index("ix_skill_packages_owner", "skill_packages", ["owner_id", "created_at"])
    op.create_table(
        "skill_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("package_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("declared_version", sa.String(128), nullable=False),
        sa.Column("description", sa.String(2000), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("tags_json", sa.Text(), nullable=False),
        sa.Column("references_json", sa.Text(), nullable=False),
        sa.Column("source_url", sa.String(2000), nullable=False),
        sa.Column("source_revision", sa.String(255), nullable=False),
        sa.Column("trust_state", sa.String(20), nullable=False),
        sa.Column("review_state", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["package_id", "owner_id"],
            ["skill_packages.id", "skill_packages.owner_id"],
            ondelete="CASCADE",
            name="fk_skill_revisions_package_scope",
        ),
        sa.UniqueConstraint("package_id", "revision_number", name="uq_skill_revision_number"),
        sa.UniqueConstraint("package_id", "content_hash", name="uq_skill_revision_content"),
        sa.UniqueConstraint("id", "package_id", "owner_id", name="uq_skill_revision_scope"),
        sa.CheckConstraint("revision_number >= 1", name="ck_skill_revision_number"),
        sa.CheckConstraint(
            "trust_state IN ('untrusted','allowlisted','verified')", name="ck_skill_trust_state"
        ),
        sa.CheckConstraint(
            "review_state IN ('pending','approved','rejected')", name="ck_skill_review_state"
        ),
    )
    op.create_index(
        "ix_skill_revisions_owner_package",
        "skill_revisions",
        ["owner_id", "package_id", "created_at"],
    )
    op.create_table(
        "project_workspaces",
        sa.Column("owner_id", sa.String(255), primary_key=True),
        sa.Column("project_id", sa.String(255), primary_key=True),
        sa.Column("current_instruction_revision_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_project_workspaces_owner_updated", "project_workspaces", ["owner_id", "updated_at"]
    )
    op.create_table(
        "project_instruction_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("review_state", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id", "project_id"],
            ["project_workspaces.owner_id", "project_workspaces.project_id"],
            ondelete="CASCADE",
            name="fk_instruction_revision_workspace",
        ),
        sa.UniqueConstraint(
            "owner_id", "project_id", "revision_number", name="uq_instruction_revision"
        ),
        sa.UniqueConstraint(
            "owner_id", "project_id", "content_hash", name="uq_instruction_content"
        ),
        sa.UniqueConstraint("id", "owner_id", "project_id", name="uq_instruction_revision_scope"),
        sa.CheckConstraint("revision_number >= 1", name="ck_instruction_revision_number"),
        sa.CheckConstraint(
            "review_state IN ('pending','approved','rejected')",
            name="ck_instruction_review_state",
        ),
    )
    op.create_index(
        "ix_instruction_revisions_scope",
        "project_instruction_revisions",
        ["owner_id", "project_id", "created_at"],
    )
    op.create_table(
        "project_skill_bindings",
        sa.Column("owner_id", sa.String(255), primary_key=True),
        sa.Column("project_id", sa.String(255), primary_key=True),
        sa.Column("package_id", sa.String(36), primary_key=True),
        sa.Column("revision_id", sa.String(36), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id", "project_id"],
            ["project_workspaces.owner_id", "project_workspaces.project_id"],
            ondelete="CASCADE",
            name="fk_skill_binding_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id", "package_id", "owner_id"],
            ["skill_revisions.id", "skill_revisions.package_id", "skill_revisions.owner_id"],
            name="fk_skill_binding_revision_scope",
        ),
    )
    op.create_index(
        "ix_skill_bindings_scope_enabled",
        "project_skill_bindings",
        ["owner_id", "project_id", "enabled"],
    )
    _create_immutability_guards()


def downgrade() -> None:
    _drop_immutability_guards()
    op.drop_table("project_skill_bindings")
    op.drop_table("project_instruction_revisions")
    op.drop_table("project_workspaces")
    op.drop_table("skill_revisions")
    op.drop_table("skill_packages")
