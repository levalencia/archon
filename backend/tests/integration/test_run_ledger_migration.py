from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command


def _config(database: Path) -> Config:
    backend = Path(__file__).parents[2]
    value = Config(str(backend / "alembic.ini"))
    value.set_main_option("script_location", str(backend / "alembic"))
    value.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database}")
    return value


def test_run_ledger_migrates_legacy_events_and_roundtrips(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ARCHON_DATABASE_URL", raising=False)
    database = tmp_path / "run-ledger-migration.db"
    alembic = _config(database)
    command.upgrade(alembic, "20260826_02")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE runtime_events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, run_id VARCHAR(36) NOT NULL, "
            "conversation_id VARCHAR(36) NOT NULL, correlation_id VARCHAR(100) NOT NULL, "
            "kind VARCHAR(40) NOT NULL, iteration INTEGER NOT NULL, data TEXT NOT NULL, "
            "created_at DATETIME)"
        )
        connection.execute("CREATE INDEX ix_runtime_events_run_id ON runtime_events (run_id)")
        connection.execute(
            "INSERT INTO runtime_events "
            "(run_id, conversation_id, correlation_id, kind, iteration, data, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy-run",
                "conversation",
                "correlation",
                "tool_call_completed",
                1,
                '{"name":"reader","result":"raw secret","status":"success"}',
                "2026-08-26 00:00:00",
            ),
        )
        connection.commit()

    command.upgrade(alembic, "head")
    engine = create_engine(f"sqlite:///{database}")
    assert {"runs", "runtime_events"} <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        run = connection.execute(text("SELECT user_id, next_sequence FROM runs")).one()
        event = connection.execute(text("SELECT sequence, payload FROM runtime_events")).one()
    assert run == ("legacy", 2)
    assert event[0] == 1
    assert "raw secret" not in event[1]
    assert '"name": "reader"' in event[1]

    command.downgrade(alembic, "20260826_02")
    assert {column["name"] for column in inspect(engine).get_columns("runtime_events")} == {
        "id",
        "run_id",
        "conversation_id",
        "correlation_id",
        "kind",
        "iteration",
        "data",
        "created_at",
    }
    command.upgrade(alembic, "head")
    assert {"runs", "runtime_events"} <= set(inspect(engine).get_table_names())
    engine.dispose()
