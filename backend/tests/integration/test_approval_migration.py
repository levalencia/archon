from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command
from app.services.db_store import Base

CORE_TABLES = (
    "users",
    "api_keys",
    "conversations",
    "messages",
    "audit_entries",
    "artifacts",
)


def config(database: Path) -> Config:
    backend = Path(__file__).parents[2]
    value = Config(str(backend / "alembic.ini"))
    value.set_main_option("script_location", str(backend / "alembic"))
    value.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database}")
    return value


def test_migration_existing_schema_downgrade_and_upgrade(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ARCHON_DATABASE_URL", raising=False)
    database = tmp_path / "migration.db"
    # Representative pre-Alembic create_all database: the baseline must adopt
    # complete core tables without recreating or dropping their data.
    legacy_engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(
        legacy_engine,
        tables=[Base.metadata.tables[name] for name in CORE_TABLES],
    )
    legacy_engine.dispose()

    alembic = config(database)
    command.upgrade(alembic, "head")
    engine = create_engine(f"sqlite:///{database}")
    inspector = inspect(engine)
    assert {
        "conversations",
        "approval_requests",
        "memory_scopes",
        "memory_facts",
        "alembic_version",
    } <= set(inspector.get_table_names())
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
    scope_columns = {column["name"] for column in inspector.get_columns("memory_scopes")}
    assert scope_columns == {"user_id", "project_id", "chars_used", "version"}
    command.downgrade(alembic, "base")
    inspector = inspect(engine)
    assert "approval_requests" not in inspector.get_table_names()
    assert "memory_scopes" not in inspector.get_table_names()
    assert "memory_facts" not in inspector.get_table_names()
    assert "conversations" in inspector.get_table_names()
    command.upgrade(alembic, "head")
    assert "approval_requests" in inspect(engine).get_table_names()
    engine.dispose()


def test_migration_fresh_database(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ARCHON_DATABASE_URL", raising=False)
    database = tmp_path / "fresh.db"
    command.upgrade(config(database), "head")
    engine = create_engine(f"sqlite:///{database}")
    assert {"approval_requests", "memory_scopes", "memory_facts", "alembic_version"} <= set(
        inspect(engine).get_table_names()
    )
    engine.dispose()
