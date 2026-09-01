from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from alembic import command


def _config(database: Path) -> Config:
    backend = Path(__file__).parents[2]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database}")
    return config


def test_instruction_snapshot_migration_roundtrip_scope_and_immutability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ARCHON_DATABASE_URL", raising=False)
    database = tmp_path / "instruction-snapshot.db"
    config = _config(database)
    command.upgrade(config, "20260901_17")
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        for owner in ("alice", "bob"):
            connection.execute(
                text(
                    "INSERT INTO project_workspaces "
                    "(owner_id,project_id,current_instruction_revision_id,created_at,updated_at) "
                    "VALUES (:owner,'shared',NULL,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                ),
                {"owner": owner},
            )
        for revision, owner, digest in (("a", "alice", "a" * 64), ("b", "bob", "b" * 64)):
            connection.execute(
                text(
                    "INSERT INTO project_instruction_revisions "
                    "(id,owner_id,project_id,revision_number,content,content_hash,"
                    "review_state,created_at) VALUES "
                    "(:revision,:owner,'shared',1,:body,:digest,'pending',CURRENT_TIMESTAMP)"
                ),
                {"revision": revision, "owner": owner, "body": owner, "digest": digest},
            )
        connection.execute(
            text(
                "UPDATE project_workspaces SET current_instruction_revision_id="
                "CASE owner_id WHEN 'alice' THEN 'b' ELSE 'b' END"
            )
        )
    engine.dispose()

    command.upgrade(config, "20260901_18")
    engine = create_engine(f"sqlite:///{database}")
    assert "project_instruction_sources" in inspect(engine).get_table_names()
    with engine.connect() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        rows = connection.execute(
            text(
                "SELECT revision_id,relative_path,scope_path,family,ordinal "
                "FROM project_instruction_sources ORDER BY revision_id"
            )
        ).all()
        assert rows == [
            ("a", ".archon/instructions.md", ".", "manual", 0),
            ("b", ".archon/instructions.md", ".", "manual", 0),
        ]
        pointers = connection.execute(
            text(
                "SELECT owner_id,current_instruction_revision_id FROM project_workspaces "
                "ORDER BY owner_id"
            )
        ).all()
        assert pointers == [("alice", None), ("bob", "b")]
        assert (
            connection.execute(
                text("SELECT review_state FROM project_instruction_revisions WHERE id='b'")
            ).scalar_one()
            == "approved"
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "UPDATE project_workspaces SET current_instruction_revision_id='b' "
                    "WHERE owner_id='alice' AND project_id='shared'"
                )
            )
        connection.rollback()
        connection.execute(text("PRAGMA foreign_keys=ON"))
        for statement in (
            "UPDATE project_instruction_revisions SET content='tampered' WHERE id='a'",
            "UPDATE project_instruction_sources SET content='tampered' WHERE revision_id='a'",
            "DELETE FROM project_instruction_sources WHERE revision_id='a'",
        ):
            with pytest.raises(IntegrityError):
                connection.execute(text(statement))
            connection.rollback()
            connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(
            text("UPDATE project_instruction_revisions SET review_state='approved' WHERE id='a'")
        )
        connection.commit()
    engine.dispose()

    command.downgrade(config, "20260901_17")
    engine = create_engine(f"sqlite:///{database}")
    assert "project_instruction_sources" not in inspect(engine).get_table_names()
    engine.dispose()
    command.upgrade(config, "20260901_18")
