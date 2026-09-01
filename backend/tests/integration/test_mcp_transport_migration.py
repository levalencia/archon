from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command


def _config(database: Path) -> Config:
    backend = Path(__file__).parents[2]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database}")
    return config


def test_transport_migration_is_linear_and_accepts_http(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ARCHON_DATABASE_URL", raising=False)
    database = tmp_path / "transport-migration.db"
    config = _config(database)
    command.upgrade(config, "20260901_17")
    command.upgrade(config, "20260901_18")
    engine = create_engine(f"sqlite:///{database}")
    constraints = {
        item["name"]: item
        for item in inspect(engine).get_check_constraints("mcp_servers")
    }
    assert "streamable_http" in constraints["ck_mcp_servers_transport"]["sqltext"]
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO mcp_servers "
                "(id,owner_id,project_id,name,profile_id,transport,enabled,health,"
                "created_at,updated_at) "
                "VALUES (:id,'o','p','remote','profile','streamable_http',0,'disabled',:now,:now)"
            ),
            {"id": "00000000-0000-0000-0000-000000000001", "now": "2026-09-01"},
        )
    command.downgrade(config, "20260901_17")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT transport FROM mcp_servers")).scalar_one() == "stdio"
    engine.dispose()
