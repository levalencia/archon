from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from alembic import command


def _config(database: Path) -> Config:
    backend = Path(__file__).parents[2]
    value = Config(str(backend / "alembic.ini"))
    value.set_main_option("script_location", str(backend / "alembic"))
    value.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database}")
    return value


def test_required_email_and_single_admin_migration_preserves_legacy_users(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("COGENTREX_DATABASE_URL", raising=False)
    database = tmp_path / "users.db"
    alembic = _config(database)
    command.upgrade(alembic, "20260917_24")

    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, username, email, password_hash, is_admin) "
                "VALUES ('u1', 'legacy', '', 'hash', 0), "
                "('u2', 'luis', ' Owner@Example.com ', 'hash', 0)"
            )
        )

    command.upgrade(alembic, "head")
    columns = {column["name"]: column for column in inspect(engine).get_columns("users")}
    assert columns["email"]["nullable"] is True

    with engine.connect() as connection:
        rows = connection.execute(text("SELECT id, email FROM users ORDER BY id")).all()
    assert rows == [("u1", None), ("u2", "owner@example.com")]

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, username, email, password_hash, is_admin) "
                "VALUES ('u3', 'normal', 'normal@example.com', 'hash', 1)"
            )
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, username, email, password_hash, is_admin) "
                "VALUES ('u4', 'duplicate-email', 'OWNER@EXAMPLE.COM', 'hash', 0)"
            )
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, username, email, password_hash, is_admin) "
                "VALUES ('u5', 'second-admin', 'second@example.com', 'hash', 1)"
            )
        )
    engine.dispose()
