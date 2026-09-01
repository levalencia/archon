from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from alembic import command


def config_for(database: Path) -> Config:
    backend = Path(__file__).parents[2]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database}")
    return config


def test_skill_instruction_migration_round_trip_and_guards(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ARCHON_DATABASE_URL", raising=False)
    database = tmp_path / "spi.db"
    config = config_for(database)
    tables = {
        "skill_packages",
        "skill_revisions",
        "project_skill_bindings",
        "project_workspaces",
        "project_instruction_revisions",
    }
    command.upgrade(config, "20260828_14")
    engine = create_engine(f"sqlite:///{database}")
    assert not tables & set(inspect(engine).get_table_names())
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database}")
    assert tables <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(
            text("INSERT INTO skill_packages VALUES ('pkg','owner','safe-skill',CURRENT_TIMESTAMP)")
        )
        connection.execute(
            text(
                "INSERT INTO skill_revisions "
                "(id,package_id,owner_id,revision_number,declared_version,description,content,"
                "content_hash,manifest_hash,tags_json,references_json,source_url,source_revision,"
                "trust_state,review_state,created_at) VALUES "
                "('rev','pkg','owner',1,'1.0','safe','content',"
                "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',"
                "'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',"
                "'[]','[]','https://raw.githubusercontent.com/n/r/p/SKILL.md','pinned',"
                "'allowlisted','approved',CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO project_workspaces "
                "(owner_id,project_id,current_instruction_revision_id,"
                "created_at,updated_at) VALUES "
                "('owner','project',NULL,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO project_instruction_revisions "
                "(id,owner_id,project_id,revision_number,content,content_hash,"
                "review_state,created_at) "
                "VALUES "
                "('inst','owner','project',1,'instructions',"
                "'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',"
                "'approved',CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO project_skill_bindings "
                "(owner_id,project_id,package_id,revision_id,enabled,created_at,updated_at) VALUES "
                "('owner','project','pkg','rev',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        connection.commit()
        for statement in (
            "UPDATE skill_revisions SET content='tampered' WHERE id='rev'",
            "DELETE FROM skill_revisions WHERE id='rev'",
            "UPDATE project_instruction_revisions SET content='tampered' WHERE id='inst'",
        ):
            with pytest.raises(IntegrityError):
                connection.execute(text(statement))
            connection.rollback()
            connection.execute(text("PRAGMA foreign_keys=ON"))
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO project_skill_bindings "
                    "(owner_id,project_id,package_id,revision_id,enabled,created_at,updated_at) "
                    "VALUES "
                    "('other','project','pkg','rev',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                )
            )
    engine.dispose()
    command.downgrade(config, "20260828_14")
    engine = create_engine(f"sqlite:///{database}")
    assert not tables & set(inspect(engine).get_table_names())
    engine.dispose()
