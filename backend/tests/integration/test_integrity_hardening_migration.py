from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from alembic import command
from app.services.db_store import MCPServerRow, ProjectSkillPinRow, SkillReferenceRow


def _config(database: Path) -> Config:
    backend = Path(__file__).parents[2]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database}")
    return config


def _revision_sql(revision: str, owner: str, package: str) -> tuple[str, dict[str, str]]:
    return (
        "INSERT INTO skill_revisions "
        "(id,package_id,owner_id,revision_number,declared_version,description,content,"
        "content_hash,manifest_hash,tags_json,references_json,triggers_json,"
        "negative_triggers_json,required_capability_ids_json,context_cost,source_url,"
        "source_revision,trust_state,review_state,created_at) VALUES "
        "(:revision,:package,:owner,1,'1','safe','body',:content_hash,:manifest_hash,"
        "'[]','[]','[]','[]','[]',1,'https://example.invalid','pinned','allowlisted',"
        "'approved',CURRENT_TIMESTAMP)",
        {
            "revision": revision,
            "package": package,
            "owner": owner,
            "content_hash": ("a" if owner == "alice" else "b") * 64,
            "manifest_hash": ("c" if owner == "alice" else "d") * 64,
        },
    )


def test_revision_owner_fences_defaults_and_complete_immutability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ARCHON_DATABASE_URL", raising=False)
    database = tmp_path / "integrity-20.db"
    config = _config(database)
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database}")
    inspector = inspect(engine)
    reference_fks = {fk["name"] for fk in inspector.get_foreign_keys("skill_references")}
    pin_fks = {fk["name"] for fk in inspector.get_foreign_keys("project_skill_pins")}
    assert "fk_skill_reference_revision_owner" in reference_fks
    assert "fk_skill_pin_revision_owner" in pin_fks

    with engine.connect() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        for package, owner in (("pkg-a", "alice"), ("pkg-b", "bob")):
            connection.execute(
                text("INSERT INTO skill_packages VALUES (:id,:owner,:name,CURRENT_TIMESTAMP)"),
                {"id": package, "owner": owner, "name": package},
            )
        for revision, owner, package in (("rev-a", "alice", "pkg-a"), ("rev-b", "bob", "pkg-b")):
            sql, values = _revision_sql(revision, owner, package)
            connection.execute(text(sql), values)
        connection.execute(
            text(
                "INSERT INTO project_workspaces VALUES "
                "('alice','project',NULL,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        connection.commit()

        for statement in (
            "INSERT INTO skill_references VALUES ('rev-a','bob','guide','x','" + "e" * 64 + "',1)",
            "INSERT INTO project_skill_pins VALUES "
            "('alice','project','rev-b','alice',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
        ):
            with pytest.raises(IntegrityError):
                connection.execute(text(statement))
            connection.rollback()
            connection.execute(text("PRAGMA foreign_keys=ON"))

        connection.execute(
            text("UPDATE skill_revisions SET review_state='pending' WHERE id='rev-a'")
        )
        connection.execute(
            text(
                "INSERT INTO skill_references VALUES "
                "('rev-a','alice','guide','x','" + "e" * 64 + "',1)"
            )
        )
        connection.execute(
            text("UPDATE skill_revisions SET review_state='approved' WHERE id='rev-a'")
        )
        connection.commit()
        for column, value in (
            ("id", "'rev-a-new'"),
            ("triggers_json", "'[\"changed\"]'"),
            ("negative_triggers_json", "'[\"changed\"]'"),
            ("required_capability_ids_json", "'[\"changed\"]'"),
            ("context_cost", "2"),
        ):
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(f"UPDATE skill_revisions SET {column}={value} WHERE id='rev-a'")
                )
            connection.rollback()
        for statement in (
            "INSERT INTO skill_references VALUES "
            "('rev-a','alice','supplement','late','" + "f" * 64 + "',4)",
            "UPDATE skill_references SET content='changed' WHERE revision_id='rev-a'",
            "DELETE FROM skill_references WHERE revision_id='rev-a'",
        ):
            with pytest.raises(IntegrityError):
                connection.execute(text(statement))
            connection.rollback()
        connection.execute(
            text("UPDATE skill_revisions SET review_state='rejected' WHERE id='rev-a'")
        )
        connection.execute(
            text(
                "INSERT INTO mcp_servers "
                "(id,owner_id,project_id,name,profile_id,transport,health,created_at,updated_at) "
                "VALUES ('server','alice','project','name','profile','stdio','disabled',"
                "CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        connection.commit()
        assert connection.execute(text("SELECT enabled FROM mcp_servers")).scalar_one() == 0
    engine.dispose()


def test_postgresql_migration_runner_uses_session_advisory_lock() -> None:
    backend = Path(__file__).parents[2]
    source = (backend / "alembic" / "env.py").read_text(encoding="utf-8")
    assert "pg_advisory_lock" in source
    assert "pg_advisory_unlock" in source
    assert "finally:" in source


def test_postgresql_schema_compiles_owner_fences_and_false_default() -> None:
    dialect = postgresql.dialect()
    reference = str(CreateTable(SkillReferenceRow.__table__).compile(dialect=dialect))
    pin = str(CreateTable(ProjectSkillPinRow.__table__).compile(dialect=dialect))
    server = str(CreateTable(MCPServerRow.__table__).compile(dialect=dialect))
    assert "fk_skill_reference_revision_owner" in reference
    assert "FOREIGN KEY(revision_id, owner_id)" in reference
    assert "fk_skill_pin_revision_owner" in pin
    assert "FOREIGN KEY(revision_id, revision_owner_id)" in pin
    assert "enabled BOOLEAN DEFAULT false NOT NULL" in server
