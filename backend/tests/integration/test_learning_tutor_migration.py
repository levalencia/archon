"""Migration contract for durable learning tutor state."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command

ROOT = Path(__file__).parents[2]


def _config(database: Path) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database}")
    return config


def test_learning_tutor_migration_round_trip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("COGENTREX_DATABASE_URL", raising=False)
    database = tmp_path / "learning-tutor.db"
    config = _config(database)

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database}")
    expected = {
        "learning_sources",
        "learning_chunks",
        "learning_tutor_sessions",
        "learning_tutor_turns",
    }
    assert expected <= set(inspect(engine).get_table_names())
    assert {column["name"] for column in inspect(engine).get_columns("learning_chunks")} >= {
        "source_id",
        "content_hash",
        "metadata_json",
        "embedding_json",
    }
    engine.dispose()

    command.downgrade(config, "20260902_22")
    engine = create_engine(f"sqlite:///{database}")
    assert not expected.intersection(inspect(engine).get_table_names())
    engine.dispose()
