"""Fence revision owners, complete immutability, and fail-closed defaults.

Revision ID: 20260901_20
Revises: 20260901_19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260901_20"
down_revision: str | None = "20260901_19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SKILL_IMMUTABLE_COLUMNS = (
    "package_id,owner_id,revision_number,declared_version,description,content,content_hash,"
    "manifest_hash,tags_json,references_json,triggers_json,negative_triggers_json,"
    "required_capability_ids_json,context_cost,source_url,source_revision,trust_state,created_at"
)


def _replace_guards(*, hardened: bool) -> None:
    dialect = op.get_bind().dialect.name
    columns = _SKILL_IMMUTABLE_COLUMNS if hardened else (
        "package_id,owner_id,revision_number,declared_version,description,content,content_hash,"
        "manifest_hash,tags_json,references_json,source_url,source_revision,trust_state,created_at"
    )
    if dialect == "sqlite":
        for name in ("trg_skill_revisions_update", "trg_skill_revisions_content_update"):
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
        op.execute(
            "CREATE TRIGGER trg_skill_revisions_content_update BEFORE UPDATE OF "
            f"{columns} ON skill_revisions "
            "BEGIN SELECT RAISE(ABORT, 'immutable revision'); END"
        )
        for operation in ("update", "delete"):
            op.execute(f"DROP TRIGGER IF EXISTS trg_skill_references_{operation}")
            if hardened:
                op.execute(
                    f"CREATE TRIGGER trg_skill_references_{operation} BEFORE {operation.upper()} "
                    "ON skill_references BEGIN SELECT RAISE(ABORT, "
                    "'immutable skill reference'); END"
                )
    elif dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_skill_revisions_immutable ON skill_revisions")
        op.execute(
            "CREATE TRIGGER trg_skill_revisions_immutable BEFORE UPDATE OF "
            f"{columns} OR DELETE ON skill_revisions FOR EACH ROW "
            "EXECUTE FUNCTION archon_spi_reject_revision_mutation()"
        )
        op.execute("DROP TRIGGER IF EXISTS trg_skill_references_immutable ON skill_references")
        if hardened:
            op.execute(
                "CREATE TRIGGER trg_skill_references_immutable BEFORE UPDATE OR DELETE "
                "ON skill_references FOR EACH ROW "
                "EXECUTE FUNCTION archon_spi_reject_revision_mutation()"
            )


def upgrade() -> None:
    bind = op.get_bind()
    bad_reference = bind.execute(
        sa.text(
            "SELECT 1 FROM skill_references AS reference WHERE NOT EXISTS "
            "(SELECT 1 FROM skill_revisions AS revision WHERE revision.id=reference.revision_id "
            "AND revision.owner_id=reference.owner_id) LIMIT 1"
        )
    ).first()
    bad_pin = bind.execute(
        sa.text(
            "SELECT 1 FROM project_skill_pins AS pin WHERE NOT EXISTS "
            "(SELECT 1 FROM skill_revisions AS revision WHERE revision.id=pin.revision_id "
            "AND revision.owner_id=pin.revision_owner_id) LIMIT 1"
        )
    ).first()
    if bad_reference is not None or bad_pin is not None:
        raise RuntimeError("cannot migrate: cross-owner skill revision reference detected")

    _replace_guards(hardened=False)
    with op.batch_alter_table("skill_revisions") as batch:
        batch.create_unique_constraint("uq_skill_revision_owner", ["id", "owner_id"])
    with op.batch_alter_table("skill_references") as batch:
        batch.create_foreign_key(
            "fk_skill_reference_revision_owner",
            "skill_revisions",
            ["revision_id", "owner_id"],
            ["id", "owner_id"],
            ondelete="CASCADE",
        )
    with op.batch_alter_table("project_skill_pins") as batch:
        batch.create_foreign_key(
            "fk_skill_pin_revision_owner",
            "skill_revisions",
            ["revision_id", "revision_owner_id"],
            ["id", "owner_id"],
        )
    with op.batch_alter_table("mcp_servers") as batch:
        batch.alter_column(
            "enabled", existing_type=sa.Boolean(), nullable=False, server_default=sa.false()
        )
    _replace_guards(hardened=True)


def downgrade() -> None:
    _replace_guards(hardened=False)
    with op.batch_alter_table("project_skill_pins") as batch:
        batch.drop_constraint("fk_skill_pin_revision_owner", type_="foreignkey")
    with op.batch_alter_table("skill_references") as batch:
        batch.drop_constraint("fk_skill_reference_revision_owner", type_="foreignkey")
    with op.batch_alter_table("skill_revisions") as batch:
        batch.drop_constraint("uq_skill_revision_owner", type_="unique")
    _replace_guards(hardened=False)
