"""SQLite round-trip and PostgreSQL compilation for MCP inventory migration."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from alembic import command
from app.services.db_store import MCPServerRow, MCPToolRow


def _config(database: Path) -> Config:
    backend = Path(__file__).parents[2]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database}")
    return config


def test_mcp_migration_round_trip_and_postgresql_safe(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ARCHON_DATABASE_URL", raising=False)
    config = _config(tmp_path / "migration.db")
    command.upgrade(config, "20260826_07")
    command.upgrade(config, "20260826_08")

    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    inspector = inspect(engine)
    assert {"mcp_servers", "mcp_tools"} <= set(inspector.get_table_names())
    foreign_keys = inspector.get_foreign_keys("mcp_tools")
    assert foreign_keys[0]["options"].get("ondelete") == "CASCADE"
    command.downgrade(config, "20260826_07")
    assert "mcp_servers" not in inspect(engine).get_table_names()
    command.upgrade(config, "20260826_08")
    engine.dispose()

    dialect = postgresql.dialect()
    server_sql = str(CreateTable(MCPServerRow.__table__).compile(dialect=dialect))
    tool_sql = str(CreateTable(MCPToolRow.__table__).compile(dialect=dialect))
    assert "mcp_servers" in server_sql
    assert "ON DELETE CASCADE" in tool_sql
