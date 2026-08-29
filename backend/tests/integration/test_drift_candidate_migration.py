"""Migration acceptance for durable drift and optimization candidate records."""

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


def test_drift_candidate_migration_round_trips(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ARCHON_DATABASE_URL", raising=False)
    database = tmp_path / "drift-candidates.db"
    config = config_for(database)
    tables = {
        "eval_cohort_revisions",
        "eval_drift_reports",
        "optimization_candidates",
        "optimization_candidate_events",
    }

    command.upgrade(config, "20260828_13")
    engine = create_engine(f"sqlite:///{database}")
    assert not tables & set(inspect(engine).get_table_names())
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO eval_runs "
                "(id,owner_id,project_id,dataset_id,dataset_version,dataset_hash,"
                "source_run_ids_json,threshold,status,passed,aggregate_metrics_json,"
                "created_at,updated_at,completed_at) VALUES "
                "('legacy-eval','owner','project','fixture','v1',"
                "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',"
                "'[]',0.8,'completed',1,'{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),"
                "('legacy-eval-2','owner','project','fixture','v1',"
                "'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',"
                "'[]',0.8,'completed',1,'{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database}")
    inspector = inspect(engine)
    assert tables <= set(inspector.get_table_names())
    with engine.connect() as connection:
        legacy = connection.execute(
            text(
                "SELECT model_revision,provider_revision,config_revision "
                "FROM eval_cohort_revisions WHERE eval_run_id='legacy-eval'"
            )
        ).one()
    assert legacy[0] == "legacy-model-unresolved"
    assert legacy[1] == "legacy-provider-unresolved"
    assert legacy[2] == "legacy-config-pre-s8.8"
    drift_insert = (
        "INSERT INTO eval_drift_reports "
        "(id,owner_id,project_id,baseline_eval_id,candidate_eval_id,"
        "baseline_identity_json,candidate_identity_json,baseline_summary_json,"
        "candidate_summary_json,deltas_json,warnings_json,minimum_sample_size,created_at) "
        "VALUES (:id,:owner,:project,'legacy-eval','legacy-eval-2','{}','{}','{}','{}','{}','[]',2,"
        "CURRENT_TIMESTAMP)"
    )
    with engine.connect() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        with pytest.raises(IntegrityError):
            connection.execute(
                text(drift_insert), {"id": "bad-scope", "owner": "other", "project": "project"}
            )
        connection.rollback()
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(
            text(drift_insert), {"id": "drift-ok", "owner": "owner", "project": "project"}
        )
        connection.commit()
        with pytest.raises(IntegrityError):
            connection.execute(
                text("UPDATE eval_drift_reports SET warnings_json='[]' WHERE id='drift-ok'")
            )
        connection.rollback()
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(
            text(
                "INSERT INTO optimization_candidates "
                "(id,owner_id,project_id,candidate_type,change_summary,proposal_metadata_json,"
                "rollback_plan,target_revision,baseline_eval_id,candidate_eval_id,"
                "drift_report_id,state,version,approval_id,created_at,updated_at,"
                "promoted_at,rolled_back_at) VALUES "
                "('candidate-ok','owner','project','config','safe change','{}','restore legacy',"
                "'config-v2','legacy-eval','legacy-eval-2','drift-ok','proposed',1,NULL,"
                "CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,NULL,NULL)"
            )
        )
        connection.commit()
        for statement in (
            "UPDATE optimization_candidates SET change_summary='tampered' WHERE id='candidate-ok'",
            "UPDATE optimization_candidates SET state='promoted',version=2 WHERE id='candidate-ok'",
            "DELETE FROM optimization_candidates WHERE id='candidate-ok'",
        ):
            with pytest.raises(IntegrityError):
                connection.execute(text(statement))
            connection.rollback()
            connection.execute(text("PRAGMA foreign_keys=ON"))
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO optimization_candidate_events "
                    "(id,candidate_id,owner_id,project_id,event_type,from_state,to_state,"
                    "candidate_version,approval_id,reason_code,created_at) VALUES "
                    "('bad-event','candidate-ok','other','project','proposed',NULL,'proposed',1,"
                    "NULL,NULL,CURRENT_TIMESTAMP)"
                )
            )
        connection.rollback()
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(
            text(
                "UPDATE optimization_candidates SET state='rejected',version=2,"
                "updated_at=CURRENT_TIMESTAMP WHERE id='candidate-ok'"
            )
        )
        connection.commit()
        assert connection.execute(
            text("SELECT state,version FROM optimization_candidates WHERE id='candidate-ok'")
        ).one() == ("rejected", 2)
    candidate_uniques = {
        item["name"] for item in inspector.get_unique_constraints("optimization_candidates")
    }
    event_uniques = {
        item["name"] for item in inspector.get_unique_constraints("optimization_candidate_events")
    }
    assert candidate_uniques == {
        "uq_candidate_approval_single_use",
        "uq_candidate_scope",
    }
    assert event_uniques == {"uq_candidate_event_version"}
    assert {item["name"] for item in inspector.get_foreign_keys("eval_drift_reports")} == {
        "fk_drift_baseline_scope",
        "fk_drift_candidate_scope",
    }
    assert {item["name"] for item in inspector.get_foreign_keys("optimization_candidates")} >= {
        "fk_candidate_baseline_scope",
        "fk_candidate_evidence_scope",
        "fk_candidate_drift_scope",
    }
    assert {
        item["name"] for item in inspector.get_foreign_keys("optimization_candidate_events")
    } == {"fk_candidate_event_scope"}
    engine.dispose()

    command.downgrade(config, "20260828_13")
    engine = create_engine(f"sqlite:///{database}")
    assert not tables & set(inspect(engine).get_table_names())
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database}")
    assert tables <= set(inspect(engine).get_table_names())
    engine.dispose()
