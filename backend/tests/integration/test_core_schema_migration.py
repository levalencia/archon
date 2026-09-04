from __future__ import annotations

import ast
import io
import sqlite3
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, select

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
CORE_METADATA = [Base.metadata.tables[name] for name in CORE_TABLES]
EXPECTED_HEAD = "20260902_22"


def _config(database: Path) -> Config:
    backend = Path(__file__).parents[2]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database}")
    return config


def _alembic_created_tables() -> set[str]:
    versions = Path(__file__).parents[2] / "alembic" / "versions"
    created: set[str] = set()
    for migration in versions.glob("*.py"):
        tree = ast.parse(migration.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "create_table"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                created.add(str(node.args[0].value))
    return created


def _index_contract(table_name: str) -> set[tuple[str, tuple[str, ...], bool]]:
    table = Base.metadata.tables[table_name]
    return {
        (str(index.name), tuple(column.name for column in index.columns), bool(index.unique))
        for index in table.indexes
    }


def _database_indexes(engine, table_name: str) -> set[tuple[str, tuple[str, ...], bool]]:
    return {
        (str(index["name"]), tuple(index["column_names"]), bool(index["unique"]))
        for index in inspect(engine).get_indexes(table_name)
    }


def _core_counts(engine) -> dict[str, int]:
    values: dict[str, int] = {}
    for name in CORE_TABLES:
        with engine.connect() as connection:
            values[name] = len(connection.execute(select(Base.metadata.tables[name])).all())
    return values


def test_every_sqlalchemy_table_has_an_alembic_create_table_owner() -> None:
    assert set(Base.metadata.tables) <= _alembic_created_tables()


def test_core_reconciliation_fresh_roundtrip_matches_models(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ARCHON_DATABASE_URL", raising=False)
    database = tmp_path / "fresh-core.db"
    config = _config(database)
    assert ScriptDirectory.from_config(config).get_heads() == [EXPECTED_HEAD]

    command.upgrade(config, "20260901_21")
    engine = create_engine(f"sqlite:///{database}")
    assert not (set(CORE_TABLES) & set(inspect(engine).get_table_names()))

    command.upgrade(config, "head")
    inspector = inspect(engine)
    assert set(CORE_TABLES) <= set(inspector.get_table_names())
    for name in CORE_TABLES:
        assert {column["name"] for column in inspector.get_columns(name)} == set(
            Base.metadata.tables[name].columns.keys()
        )
        assert _database_indexes(engine, name) == _index_contract(name)
        assert all(column["default"] is None for column in inspector.get_columns(name))
        assert inspector.get_pk_constraint(name)["constrained_columns"] == ["id"]

    command.downgrade(config, "20260901_21")
    assert set(CORE_TABLES) <= set(inspect(engine).get_table_names())
    command.upgrade(config, "head")
    assert set(CORE_TABLES) <= set(inspect(engine).get_table_names())
    engine.dispose()


@pytest.mark.parametrize(
    "starting_revision",
    [
        "20260826_01",
        "20260826_08",
        "20260828_14",
        "20260901_20",
        "20260901_21",
    ],
)
def test_stamped_historical_database_missing_core_is_reconciled(
    tmp_path: Path, monkeypatch, starting_revision: str
) -> None:
    monkeypatch.delenv("ARCHON_DATABASE_URL", raising=False)
    database = tmp_path / f"missing-{starting_revision}.db"
    config = _config(database)
    command.upgrade(config, starting_revision)
    engine = create_engine(f"sqlite:///{database}")
    assert not (set(CORE_TABLES) & set(inspect(engine).get_table_names()))
    command.upgrade(config, "head")
    assert set(CORE_TABLES) <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert (
            connection.execute(
                Base.metadata.tables["users"]
                .insert()
                .values(
                    id="user",
                    username=f"user-{starting_revision}",
                    email="",
                    password_hash="hash",
                    is_admin=0,
                )
            ).rowcount
            == 1
        )
        connection.commit()
    engine.dispose()


def test_core_reconciliation_adopts_legacy_schema_without_losing_rows(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("ARCHON_DATABASE_URL", raising=False)
    database = tmp_path / "legacy-core.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine, tables=CORE_METADATA)
    tables = Base.metadata.tables
    with engine.begin() as connection:
        connection.execute(
            tables["users"]
            .insert()
            .values(id="user", username="legacy", email="", password_hash="hash", is_admin=0)
        )
        connection.execute(
            tables["api_keys"]
            .insert()
            .values(id="key", key_hash="a" * 64, user_id="user", name="legacy")
        )
        connection.execute(
            tables["conversations"]
            .insert()
            .values(id="conversation", title="Legacy", user_id="user", is_active=1)
        )
        connection.execute(
            tables["messages"]
            .insert()
            .values(conversation_id="conversation", role="user", content="hello")
        )
        connection.execute(
            tables["audit_entries"]
            .insert()
            .values(
                timestamp="2026-09-02T00:00:00Z",
                agent_id="agent",
                action="test",
                resource="legacy",
            )
        )
        connection.execute(
            tables["artifacts"]
            .insert()
            .values(
                id="artifact",
                conversation_id="conversation",
                title="Legacy",
                artifact_type="text",
                content="body",
            )
        )
        connection.exec_driver_sql("CREATE INDEX ix_users_email_ops ON users(email)")
    before = _core_counts(engine)

    config = _config(database)
    command.upgrade(config, "head")
    assert _core_counts(engine) == before
    command.downgrade(config, "20260901_21")
    assert _core_counts(engine) == before
    command.upgrade(config, "head")
    assert _core_counts(engine) == before
    engine.dispose()


def _malformed_users_sql(change: str) -> str:
    columns = {
        "id": "VARCHAR(36) PRIMARY KEY",
        "username": "VARCHAR(50) NOT NULL",
        "email": "VARCHAR(320) NOT NULL",
        "password_hash": "TEXT NOT NULL",
        "is_admin": "INTEGER NOT NULL",
    }
    name, definition = change.split("=", 1)
    columns[name] = definition
    return (
        "CREATE TABLE users ("
        + ",".join(f"{name} {value}" for name, value in columns.items())
        + ")"
    )


@pytest.mark.parametrize(
    "change",
    [
        "id=CHAR(36) PRIMARY KEY",
        "username=VARCHAR(20) NOT NULL",
        "is_admin=SMALLINT NOT NULL",
        "is_admin=BIGINT NOT NULL",
        "is_admin=VARCHAR(10) NOT NULL",
        "email=VARCHAR(320) NOT NULL DEFAULT ''",
    ],
)
def test_core_reconciliation_rejects_incompatible_legacy_contract(
    tmp_path: Path, monkeypatch, change: str
) -> None:
    monkeypatch.delenv("ARCHON_DATABASE_URL", raising=False)
    database = tmp_path / "incompatible-core.db"
    config = _config(database)
    command.upgrade(config, "20260901_21")
    with sqlite3.connect(database) as connection:
        connection.execute(_malformed_users_sql(change))
        connection.execute("CREATE UNIQUE INDEX ix_users_username ON users(username)")
    with pytest.raises(RuntimeError, match="users.*contract mismatch"):
        command.upgrade(config, "head")


def test_core_reconciliation_rejects_partial_legacy_table(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ARCHON_DATABASE_URL", raising=False)
    database = tmp_path / "partial-core.db"
    config = _config(database)
    command.upgrade(config, "20260901_21")
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)")
    with pytest.raises(RuntimeError, match="users.*column contract"):
        command.upgrade(config, "head")


def test_core_reconciliation_offline_sql_fails_closed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ARCHON_DATABASE_URL", raising=False)
    output = io.StringIO()
    config = _config(tmp_path / "offline.db")
    config.output_buffer = output
    with pytest.raises(RuntimeError, match="requires online Alembic"):
        command.upgrade(config, "20260901_21:20260902_22", sql=True)


# ---------------------------------------------------------------------------
# PostgreSQL-representative legacy server-default regression tests
# ---------------------------------------------------------------------------
# SQLite reflects DEFAULT values as bare strings; PostgreSQL adds type casts
# (e.g. ''::character varying).  We monkey-patch the reflected column metadata
# to simulate the exact PostgreSQL-style defaults from the retained database.


def _patch_inspector_columns_with_pg_defaults(engine, monkeypatch):
    """Override reflected ``get_columns`` to inject PG-style server defaults."""
    pg_defaults: dict[str, dict[str, str]] = {
        "users": {"email": "''::character varying", "is_admin": "0"},
        "conversations": {
            "title": "'New Conversation'::character varying",
            "user_id": "'default'::character varying",
            "is_active": "1",
        },
        "audit_entries": {
            "result": "'success'::character varying",
            "security_level": "'info'::character varying",
        },
        "artifacts": {"version": "1"},
        "messages": {},
        "api_keys": {},
    }
    from sqlalchemy.engine.reflection import Inspector

    original_get_columns = Inspector.get_columns

    def patched_get_columns(self, table_name, *args, **kwargs):
        cols = original_get_columns(self, table_name, *args, **kwargs)
        defaults = pg_defaults.get(table_name, {})
        for col in cols:
            if col["name"] in defaults:
                col["default"] = defaults[col["name"]]
        return cols

    monkeypatch.setattr(Inspector, "get_columns", patched_get_columns)


def test_known_pg_legacy_defaults_accepted(tmp_path: Path, monkeypatch) -> None:
    """Known historical PG server defaults must be accepted during adoption."""
    monkeypatch.delenv("ARCHON_DATABASE_URL", raising=False)
    database = tmp_path / "pg-defaults.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[t] for t in CORE_TABLES])
    engine.dispose()

    _patch_inspector_columns_with_pg_defaults(engine, monkeypatch)

    config = _config(database)
    # Must succeed — known legacy defaults should be accepted
    command.upgrade(config, "head")


def test_unknown_pg_server_default_rejected(tmp_path: Path, monkeypatch) -> None:
    """An unexpected server default must still trigger fail-closed RuntimeError."""
    monkeypatch.delenv("ARCHON_DATABASE_URL", raising=False)
    database = tmp_path / "bad-pg-defaults.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[t] for t in CORE_TABLES])
    engine.dispose()

    from sqlalchemy.engine.reflection import Inspector

    original_get_columns = Inspector.get_columns

    def inject_bad_default(self, table_name, *args, **kwargs):
        cols = original_get_columns(self, table_name, *args, **kwargs)
        if table_name == "users":
            for col in cols:
                if col["name"] == "email":
                    col["default"] = "'HACKED'::character varying"
        return cols

    monkeypatch.setattr(Inspector, "get_columns", inject_bad_default)

    config = _config(database)
    with pytest.raises(RuntimeError, match="users.email server-default contract mismatch"):
        command.upgrade(config, "head")


def test_known_pg_defaults_with_data_preserved(tmp_path: Path, monkeypatch) -> None:
    """Adoption with known PG defaults must preserve existing row data."""
    monkeypatch.delenv("ARCHON_DATABASE_URL", raising=False)
    database = tmp_path / "pg-defaults-data.db"
    engine = create_engine(f"sqlite:///{database}")
    tables = Base.metadata.tables
    Base.metadata.create_all(engine, tables=[tables[t] for t in CORE_TABLES])
    with engine.begin() as conn:
        conn.execute(
            tables["users"]
            .insert()
            .values(id="u1", username="pguser", email="", password_hash="h", is_admin=0)
        )
        conn.execute(
            tables["conversations"]
            .insert()
            .values(id="c1", title="New Conversation", user_id="default", is_active=1)
        )
    before = _core_counts(engine)
    engine.dispose()

    _patch_inspector_columns_with_pg_defaults(engine, monkeypatch)

    config = _config(database)
    command.upgrade(config, "head")

    engine2 = create_engine(f"sqlite:///{database}")
    assert _core_counts(engine2) == before
    engine2.dispose()
