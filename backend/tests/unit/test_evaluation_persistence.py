"""Persistence-only tests for durable evaluation records."""

from __future__ import annotations

import math
import sqlite3
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from app.eval.persistence import EvaluationRepository
from app.services.db_store import DatabaseStore, EvalRunRow

_HASH = "a" * 64


@pytest.mark.asyncio
async def test_repository_is_owner_scoped_and_survives_restart(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'evaluations.db'}"
    store = DatabaseStore(url)
    await store.initialize()
    repository = EvaluationRepository(store.session_factory)
    created = await repository.create(
        "alice",
        project_id="alpha",
        dataset_id="grounded-v1",
        dataset_version="1.0.0",
        dataset_hash=_HASH,
        source_run_ids=("run-1",),
        threshold=0.8,
    )
    case = await repository.append_case(
        "alice",
        created.id,
        source_run_id="run-1",
        case_key="citation",
        passed=True,
        score=0.9,
        metrics={"coverage": 0.9},
        checks=({"name": "citation", "passed": True},),
    )
    completed = await repository.finalize(
        "alice",
        created.id,
        status="completed",
        passed=True,
        aggregate_metrics={"mean_score": 0.9, "case_count": 1},
    )
    assert len(completed.cases) == 1
    assert completed.cases[0].id == case.id
    assert await repository.get("mallory", created.id) is None
    assert await repository.list("mallory") == ()
    assert [item.id for item in await repository.list("alice", project_id="alpha")] == [created.id]
    with pytest.raises(FrozenInstanceError):
        completed.status = "failed"  # type: ignore[misc]
    await store.close()

    restarted = DatabaseStore(url)
    await restarted.initialize()
    persisted = await EvaluationRepository(restarted.session_factory).get("alice", created.id)
    assert persisted is not None
    assert persisted.status == "completed"
    assert persisted.cases[0].score == 0.9
    with pytest.raises(ValueError, match="running evaluation not found"):
        await EvaluationRepository(restarted.session_factory).append_case(
            "alice",
            created.id,
            source_run_id="run-1",
            case_key="late",
            passed=True,
            score=1.0,
            metrics={},
            checks=(),
        )
    await restarted.close()


@pytest.mark.asyncio
async def test_repository_rejects_unsafe_json_and_non_finite_scores(tmp_path: Path) -> None:
    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path / 'safe.db'}")
    await store.initialize()
    repository = EvaluationRepository(store.session_factory)
    created = await repository.create(
        "alice",
        project_id="alpha",
        dataset_id="dataset",
        dataset_version="1",
        dataset_hash=_HASH,
        source_run_ids=("run-1",),
        threshold=0.5,
    )
    with pytest.raises(ValueError, match="finite"):
        await repository.append_case(
            "alice",
            created.id,
            source_run_id="run-1",
            case_key="bad",
            passed=False,
            score=math.nan,
            metrics={},
            checks=(),
        )
    with pytest.raises(ValueError, match="raw answers or events"):
        await repository.append_case(
            "alice",
            created.id,
            source_run_id="run-1",
            case_key="unsafe",
            passed=False,
            score=0.0,
            metrics={"raw_answer": "must not persist"},
            checks=(),
        )
    await store.close()


@pytest.mark.asyncio
async def test_database_constraints_and_case_cascade(tmp_path: Path) -> None:
    database = tmp_path / "constraints.db"
    store = DatabaseStore(f"sqlite+aiosqlite:///{database}")
    await store.initialize()
    async with store.session_factory() as session:
        session.add(
            EvalRunRow(
                id="eval-bad",
                owner_id="alice",
                project_id="alpha",
                dataset_id="dataset",
                dataset_version="1",
                dataset_hash=_HASH,
                source_run_ids_json=["run-1"],
                threshold=2.0,
                status="running",
                passed=None,
                aggregate_metrics_json={},
                created_at=datetime.now(tz=UTC),
                updated_at=datetime.now(tz=UTC),
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
    await store.close()

    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(eval_case_results)")}
        assert "score" in columns
        foreign_keys = list(connection.execute("PRAGMA foreign_key_list(eval_case_results)"))
        assert any(row[2] == "eval_runs" and row[6] == "CASCADE" for row in foreign_keys)
        connection.execute(
            """INSERT INTO eval_runs VALUES (
                'eval-ok','alice','alpha','dataset','1',?, '[\"run-1\"]',0.5,
                'running',NULL,'{}',?,?,NULL
            )""",
            (_HASH, "2026-08-26T00:00:00Z", "2026-08-26T00:00:00Z"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT INTO eval_case_results VALUES (
                    'case-bad','eval-ok','run-1','bad',1,2.0,'{}','[]',?
                )""",
                ("2026-08-26T00:00:00Z",),
            )
        connection.execute(
            """INSERT INTO eval_case_results VALUES (
                'case-ok','eval-ok','run-1','ok',1,1.0,'{}','[]',?
            )""",
            ("2026-08-26T00:00:00Z",),
        )
        connection.execute("DELETE FROM eval_runs WHERE id='eval-ok'")
        assert connection.execute("SELECT count(*) FROM eval_case_results").fetchone()[0] == 0
    finally:
        connection.close()
