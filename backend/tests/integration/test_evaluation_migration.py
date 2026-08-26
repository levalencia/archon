"""SQLite migration round-trip for durable evaluation tables."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command


def _config(database: Path) -> Config:
    backend = Path(__file__).parents[2]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database}")
    return config


def test_evaluation_migration_round_trip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ARCHON_DATABASE_URL", raising=False)
    database = tmp_path / "migration.db"
    config = _config(database)
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database}")
    inspector = inspect(engine)
    assert {"eval_runs", "eval_case_results"} <= set(inspector.get_table_names())
    assert {column["name"] for column in inspector.get_columns("eval_case_results")} >= {
        "id",
        "eval_run_id",
        "source_run_id",
        "case_key",
        "passed",
        "score",
        "metrics_json",
        "checks_json",
    }
    command.downgrade(config, "20260826_05")
    assert "eval_runs" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    assert "eval_runs" in inspect(engine).get_table_names()
    engine.dispose()
