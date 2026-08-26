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


def test_postgresql_collision_objects_are_renamed_before_replacement_table() -> None:
    """Guard the PostgreSQL-only DDL that SQLite cannot exercise."""
    backend = Path(__file__).parents[2]
    migration = (backend / "alembic/versions/20260826_03_run_ledger.py").read_text()
    rename_table = migration.index('op.rename_table("runtime_events", "runtime_events_legacy")')
    prepare_legacy = migration.index("_prepare_postgresql_legacy_table(connection)", rename_table)
    create_replacement = migration.index("_create_runs()", prepare_legacy)

    assert rename_table < prepare_legacy < create_replacement
    assert 'get_pk_constraint("runtime_events_legacy")' in migration
    assert "quote = preparer.quote_identifier" in migration
    assert "pg_get_serial_sequence(:table_name, :column_name)" in migration
    assert "quote('runtime_events_legacy_id_seq')" in migration


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
        run = connection.execute(
            text("SELECT user_id, status, completed_at, next_sequence FROM runs")
        ).one()
        event = connection.execute(text("SELECT sequence, payload FROM runtime_events")).one()
    assert run[0:2] == ("legacy", "completed")
    assert run[2] is not None
    assert run[3] == 2
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
    with engine.begin() as connection:
        inserted_id = connection.execute(
            text(
                "INSERT INTO runtime_events "
                "(run_id, conversation_id, correlation_id, kind, iteration, data, created_at) "
                "VALUES ('legacy-run-2', 'conversation', 'correlation', 'run_started', 1, '{}', "
                "CURRENT_TIMESTAMP) RETURNING id"
            )
        ).scalar_one()
    assert inserted_id == 2
    command.upgrade(alembic, "head")
    assert {"runs", "runtime_events"} <= set(inspect(engine).get_table_names())
    engine.dispose()
