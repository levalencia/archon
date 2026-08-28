"""Migration coverage for secure exports and shares."""

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command


def _config(database: Path) -> Config:
    backend = Path(__file__).parents[2]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database}")
    return config


@pytest.mark.integration
def test_migration_10_to_11_to_12(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARCHON_DATABASE_URL", raising=False)
    database = tmp_path / "migration.db"
    config = _config(database)
    command.upgrade(config, "20260827_10")
    command.upgrade(config, "20260827_11")
    command.upgrade(config, "20260828_12")
    engine = create_engine(f"sqlite:///{database}")
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {"run_exports", "run_share_grants"} <= tables
    assert "manifest_checksum" in {item["name"] for item in inspector.get_columns("run_exports")}
    assert {
        "ck_run_exports_schema_version",
    } <= {item["name"] for item in inspector.get_check_constraints("run_exports")}
    assert {
        "ck_share_purpose",
        "ck_share_expiry_after_create",
        "ck_share_revoked_after_create",
    } <= {item["name"] for item in inspector.get_check_constraints("run_share_grants")}
    foreign_keys = inspector.get_foreign_keys("run_share_grants")
    assert any(
        item["constrained_columns"] == ["export_id", "owner_id"]
        and item["referred_table"] == "run_exports"
        for item in foreign_keys
    )
    with engine.connect() as connection:
        assert (
            connection.execute(text("select version_num from alembic_version")).scalar_one()
            == "20260828_12"
        )
    engine.dispose()

    command.downgrade(config, "20260827_11")
    downgraded = create_engine(f"sqlite:///{database}")
    assert "run_exports" not in inspect(downgraded).get_table_names()
    assert "run_share_grants" not in inspect(downgraded).get_table_names()
    downgraded.dispose()

    command.upgrade(config, "head")
    restored = create_engine(f"sqlite:///{database}")
    assert {"run_exports", "run_share_grants"} <= set(inspect(restored).get_table_names())
    restored.dispose()
