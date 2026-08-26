from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command


def config(database: Path) -> Config:
    backend = Path(__file__).parents[2]
    value = Config(str(backend / "alembic.ini"))
    value.set_main_option("script_location", str(backend / "alembic"))
    value.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database}")
    return value


def test_migration_existing_schema_downgrade_and_upgrade(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ARCHON_DATABASE_URL", raising=False)
    database = tmp_path / "migration.db"
    # Representative pre-Alembic create_all database: migration must preserve existing tables.
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE conversations (id VARCHAR(36) PRIMARY KEY)")
        connection.commit()

    alembic = config(database)
    command.upgrade(alembic, "head")
    engine = create_engine(f"sqlite:///{database}")
    inspector = inspect(engine)
    assert {"conversations", "approval_requests", "alembic_version"} <= set(
        inspector.get_table_names()
    )
    columns = {column["name"] for column in inspector.get_columns("approval_requests")}
    assert columns == {
        "id",
        "user_id",
        "conversation_id",
        "run_id",
        "tool_call_id",
        "tool_name",
        "arguments_hash",
        "risk_classes",
        "matched_rule_id",
        "status",
        "decision_reason",
        "created_at",
        "expires_at",
        "decided_at",
    }
    indexes = {index["name"] for index in inspector.get_indexes("approval_requests")}
    assert indexes == {
        "ix_approval_requests_owner",
        "ix_approval_requests_status",
        "ix_approval_requests_run",
        "ix_approval_requests_call",
    }
    command.downgrade(alembic, "base")
    inspector = inspect(engine)
    assert "approval_requests" not in inspector.get_table_names()
    assert "conversations" in inspector.get_table_names()
    command.upgrade(alembic, "head")
    assert "approval_requests" in inspect(engine).get_table_names()
    engine.dispose()


def test_migration_fresh_database(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ARCHON_DATABASE_URL", raising=False)
    database = tmp_path / "fresh.db"
    command.upgrade(config(database), "head")
    engine = create_engine(f"sqlite:///{database}")
    assert {"approval_requests", "alembic_version"} <= set(inspect(engine).get_table_names())
    engine.dispose()
