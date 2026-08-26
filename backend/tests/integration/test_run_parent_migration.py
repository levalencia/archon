"""Migration coverage for the run self-referential lineage constraint."""

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


def _insert_run(connection: object, run_id: str, parent_run_id: str | None) -> None:
    connection.execute(  # type: ignore[attr-defined]
        text(
            "INSERT INTO runs (run_id,user_id,project_id,conversation_id,correlation_id,"
            "parent_run_id,provider,model,schema_version,status,started_at,input_tokens,"
            "output_tokens,total_tokens,iterations,next_sequence) VALUES "
            "(:run_id,'alice','alpha','conversation','correlation',:parent,'mock','model',1,"
            "'running',CURRENT_TIMESTAMP,0,0,0,0,1)"
        ),
        {"run_id": run_id, "parent": parent_run_id},
    )


def test_run_parent_fk_migrates_valid_rows_and_roundtrips(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ARCHON_DATABASE_URL", raising=False)
    database = tmp_path / "run-parent-fk.db"
    config = _config(database)
    command.upgrade(config, "20260826_06")
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        _insert_run(connection, "root", None)
        _insert_run(connection, "child", "root")

    command.upgrade(config, "head")
    # SQLite connections cache schema metadata across an external table rebuild.
    engine.dispose()
    engine = create_engine(f"sqlite:///{database}")
    foreign_keys = inspect(engine).get_foreign_keys("runs")
    assert any(
        item["referred_table"] == "runs"
        and item["constrained_columns"] == ["parent_run_id"]
        and item["options"].get("ondelete") == "RESTRICT"
        for item in foreign_keys
    )
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        with pytest.raises(IntegrityError):
            _insert_run(connection, "orphan", "missing")
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        with pytest.raises(IntegrityError):
            connection.execute(text("DELETE FROM runs WHERE run_id='root'"))

    command.downgrade(config, "20260826_06")
    assert not inspect(engine).get_foreign_keys("runs")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        parent_id = connection.execute(
            text("SELECT parent_run_id FROM runs WHERE run_id='child'")
        ).scalar()
        assert parent_id == "root"
    engine.dispose()
