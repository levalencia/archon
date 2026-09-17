"""Forward-removal migration contract for contextual Learning Tutor state."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command

ROOT = Path(__file__).parents[2]
TUTOR_TABLES = {
    "learning_sources",
    "learning_chunks",
    "learning_tutor_sessions",
    "learning_tutor_turns",
}


def _config(database: Path) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database}")
    return config


def _tables(database: Path) -> set[str]:
    engine = create_engine(f"sqlite:///{database}")
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_learning_tutor_tables_are_removed_at_head_and_restorable(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("COGENTREX_DATABASE_URL", raising=False)
    database = tmp_path / "learning-tutor-removal.db"
    config = _config(database)

    command.upgrade(config, "20260912_23")
    assert _tables(database) >= TUTOR_TABLES

    command.upgrade(config, "head")
    assert TUTOR_TABLES.isdisjoint(_tables(database))

    command.downgrade(config, "20260912_23")
    assert _tables(database) >= TUTOR_TABLES

    command.upgrade(config, "head")
    assert TUTOR_TABLES.isdisjoint(_tables(database))
