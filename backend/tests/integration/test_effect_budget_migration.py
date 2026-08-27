"""Migration and metadata coverage for effects and monetary reservations."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from alembic import command
from app.services.db_store import (
    EffectRow,
    ModelChargeRow,
    ProjectBudgetRow,
    RunRow,
)


def _config(database: Path) -> Config:
    backend = Path(__file__).parents[2]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database}")
    return config


def _names(items: list[dict[str, object]]) -> set[str]:
    return {str(item["name"]) for item in items}


def test_effect_budget_migration_is_single_head_and_round_trips(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("ARCHON_DATABASE_URL", raising=False)
    database = tmp_path / "effect-budget.db"
    config = _config(database)
    assert ScriptDirectory.from_config(config).get_heads() == ["20260827_10"]

    command.upgrade(config, "20260826_08")
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO runs (run_id,user_id,project_id,conversation_id,correlation_id,"
                "provider,model,schema_version,status,started_at,input_tokens,output_tokens,"
                "total_tokens,iterations,next_sequence) VALUES "
                "('existing','alice','alpha','conversation','correlation','mock','model',1,"
                "'running',CURRENT_TIMESTAMP,0,0,0,0,1)"
            )
        )

    command.upgrade(config, "head")
    engine.dispose()
    engine = create_engine(f"sqlite:///{database}")
    inspector = inspect(engine)
    assert {
        "effects",
        "project_budgets",
        "model_charges",
        "context_snapshots",
        "memory_key_state",
    } <= set(inspector.get_table_names())
    assert {
        "budget_limit_nusd",
        "budget_spent_nusd",
        "budget_reserved_nusd",
        "budget_opened_at",
    } <= _names(inspector.get_columns("runs"))
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT budget_limit_nusd,budget_spent_nusd,budget_reserved_nusd "
                "FROM runs WHERE run_id='existing'"
            )
        ).one() == (0, 0, 0)

    assert _names(inspector.get_check_constraints("effects")) == {
        "ck_effects_identity_version_nonnegative",
        "ck_effects_output_size_nonnegative",
        "ck_effects_state",
    }
    assert {
        "ix_effects_owner_project_state",
        "ix_effects_owner_run",
        "ix_effects_run_state",
    } <= _names(inspector.get_indexes("effects"))
    assert _names(inspector.get_check_constraints("project_budgets")) == {
        "ck_project_budgets_amounts_nonnegative",
        "ck_project_budgets_within_limit",
    }
    assert {
        "ck_model_charges_actual_nonnegative",
        "ck_model_charges_ordinal_nonnegative",
        "ck_model_charges_reserved_nonnegative",
        "ck_model_charges_state",
        "ck_model_charges_tokens_nonnegative",
    } == _names(inspector.get_check_constraints("model_charges"))
    assert "uq_model_charges_run_ordinal" in _names(
        inspector.get_unique_constraints("model_charges")
    )
    assert {"ix_model_charges_owner_project_state", "ix_model_charges_run_state"} <= _names(
        inspector.get_indexes("model_charges")
    )
    assert {
        "ck_runs_budget_amounts_nonnegative",
        "ck_runs_budget_within_limit",
    } <= _names(inspector.get_check_constraints("runs"))
    assert _names(inspector.get_check_constraints("context_snapshots")) == {
        "ck_context_snapshots_schema_version",
        "ck_context_snapshots_tokens_nonnegative",
    }
    assert "uq_context_snapshots_run" in _names(
        inspector.get_unique_constraints("context_snapshots")
    )
    assert {
        "ix_context_snapshots_owner_run",
        "ix_context_snapshots_owner_project_created",
    } <= _names(inspector.get_indexes("context_snapshots"))
    context_foreign_keys = inspector.get_foreign_keys("context_snapshots")
    assert len(context_foreign_keys) == 1
    assert context_foreign_keys[0]["referred_table"] == "runs"
    assert context_foreign_keys[0]["constrained_columns"] == ["run_id"]
    assert _names(inspector.get_check_constraints("memory_key_state")) == {
        "ck_memory_key_state_active",
        "ck_memory_key_state_generation",
    }
    assert "ck_memory_facts_key_version" in _names(
        inspector.get_check_constraints("memory_facts")
    )

    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            text(
                "INSERT INTO project_budgets "
                "(owner_id,project_id,limit_nusd,spent_nusd,reserved_nusd,updated_at) "
                "VALUES ('alice','alpha',10,8,3,CURRENT_TIMESTAMP)"
            )
        )

    command.downgrade(config, "20260826_08")
    engine.dispose()
    engine = create_engine(f"sqlite:///{database}")
    downgraded = inspect(engine)
    assert not (
        {
            "effects",
            "project_budgets",
            "model_charges",
            "context_snapshots",
            "memory_key_state",
        }
        & set(downgraded.get_table_names())
    )
    assert not {
        "budget_limit_nusd",
        "budget_spent_nusd",
        "budget_reserved_nusd",
        "budget_opened_at",
    } & _names(downgraded.get_columns("runs"))
    assert "ck_memory_facts_key_version" not in _names(
        downgraded.get_check_constraints("memory_facts")
    )

    command.upgrade(config, "head")
    engine.dispose()
    engine = create_engine(f"sqlite:///{database}")
    assert {
        "effects",
        "project_budgets",
        "model_charges",
        "context_snapshots",
        "memory_key_state",
    } <= set(inspect(engine).get_table_names())
    engine.dispose()


def test_effect_and_charge_metadata_store_only_safe_bounded_fields() -> None:
    effect_columns = set(EffectRow.__table__.columns.keys())
    assert effect_columns == {
        "effect_id",
        "identity_version",
        "owner_id",
        "project_id",
        "run_id",
        "tool_name",
        "schema_hash",
        "state",
        "output_hash",
        "output_size",
        "failure_code",
        "review_disposition",
        "reviewed_by",
        "reserved_at",
        "completed_at",
        "reviewed_at",
    }
    assert not EffectRow.__table__.c.run_id.foreign_keys
    assert set(ModelChargeRow.__table__.columns.keys()) == {
        "charge_id",
        "owner_id",
        "project_id",
        "run_id",
        "ordinal",
        "state",
        "reserved_nusd",
        "actual_nusd",
        "provider",
        "model",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "reason_code",
        "created_at",
        "updated_at",
        "dispatched_at",
        "reconciled_at",
    }
    assert ProjectBudgetRow.__table__.c.limit_nusd.type.python_type is int
    assert RunRow.__table__.c.budget_limit_nusd.type.python_type is int
    dialect = postgresql.dialect()
    for table in (EffectRow.__table__, ProjectBudgetRow.__table__, ModelChargeRow.__table__):
        ddl = str(CreateTable(table).compile(dialect=dialect))
        assert "BIGINT" in ddl
        assert "CHECK" in ddl
