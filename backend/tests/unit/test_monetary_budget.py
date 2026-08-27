"""Exact pricing and durable monetary accounting tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.observability.cost_tracker import (
    UnknownModelPricing,
    price_model_usage_nusd,
    quote_model_call_nusd,
)
from app.services.db_store import Base, ModelChargeRow, RunRow
from app.services.monetary_budget import (
    BudgetLimitConflict,
    ChargeState,
    ChargeStateConflict,
    MonetaryBudgetRepository,
    ProjectBudgetExceeded,
    QuoteExceeded,
    RunBudgetExceeded,
)


def test_exact_pricing_cache_unknown_and_bounds() -> None:
    assert price_model_usage_nusd("gpt-4o", "openai", 1_000, 1_000) == 12_500_000
    assert price_model_usage_nusd("claude-opus-4-6", "anthropic", 1_000, 0, 100, 100) == 4_675_000
    # Cache reports do not get unpublished/unsupported discounts.
    assert price_model_usage_nusd("claude-opus-4-6", "other", 1_000, 0, 100, 100) == 5_000_000
    assert (
        quote_model_call_nusd([("openai", "gpt-4o-mini"), ("openai", "gpt-4o")], 1_000, 1_000)
        == 12_500_000
    )
    with pytest.raises(UnknownModelPricing):
        price_model_usage_nusd("missing", "openai", 1, 1)
    for invalid in (-1, True, 2**63):
        with pytest.raises((TypeError, ValueError, OverflowError)):
            price_model_usage_nusd("gpt-4o", "openai", invalid, 0)  # type: ignore[arg-type]
    with pytest.raises(OverflowError):
        price_model_usage_nusd("gpt-4-turbo", "openai", 2**63 - 1, 0)


async def _repository(path: Path) -> tuple[MonetaryBudgetRepository, async_sessionmaker, object]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", connect_args={"timeout": 30})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return MonetaryBudgetRepository(sessions), sessions, engine


async def _run(sessions: async_sessionmaker, run_id: str, owner: str = "alice") -> None:
    async with sessions() as session:
        session.add(
            RunRow(
                run_id=run_id,
                user_id=owner,
                project_id="project",
                conversation_id=run_id,
                correlation_id=run_id,
                provider="mock",
                model="mock-model",
                status="running",
                started_at=datetime.now(tz=UTC),
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_limits_duplicates_reconcile_release_and_restart(tmp_path: Path) -> None:
    database = tmp_path / "money.db"
    repository, sessions, engine = await _repository(database)
    await _run(sessions, "run-1")
    await repository.open_run("alice", "project", "run-1", 100, 150)
    await repository.open_run("alice", "project", "run-1", 100, 150)
    with pytest.raises(BudgetLimitConflict):
        await repository.open_run("alice", "project", "run-1", 101, 150)

    first = await repository.reserve_call(
        "charge-1", "alice", "project", "run-1", 0, 100, "mock", "mock-model"
    )
    assert first.should_dispatch
    duplicate = await repository.reserve_call(
        "charge-1", "alice", "project", "run-1", 0, 100, "mock", "mock-model"
    )
    assert not duplicate.should_dispatch
    with pytest.raises(RunBudgetExceeded):
        await repository.reserve_call(
            "charge-2", "alice", "project", "run-1", 1, 1, "mock", "mock-model"
        )
    await repository.mark_dispatched("charge-1", "alice", "project", "run-1")
    charge = await repository.reconcile("charge-1", "alice", "project", "run-1", 75, 10, 5)
    assert charge.state is ChargeState.RECONCILED
    summary = await repository.summary(owner_id="alice", project_id="project", run_id="run-1")
    assert summary is not None
    assert (summary.run_spent_nusd, summary.run_reserved_nusd) == (75, 0)

    equal = await repository.reserve_call(
        "charge-3", "alice", "project", "run-1", 2, 25, "mock", "mock-model"
    )
    assert equal.should_dispatch
    await repository.mark_dispatched("charge-3", "alice", "project", "run-1")
    await repository.reconcile("charge-3", "alice", "project", "run-1", 25, 1, 1)

    await engine.dispose()
    restarted, _, restarted_engine = await _repository(database)
    durable = await restarted.summary(owner_id="alice", project_id="project", run_id="run-1")
    assert durable is not None and durable.project_spent_nusd == 100
    await restarted_engine.dispose()


@pytest.mark.asyncio
async def test_project_aggregate_concurrency_overquote_release_and_recovery(tmp_path: Path) -> None:
    repository, sessions, engine = await _repository(tmp_path / "concurrent.db")
    await _run(sessions, "run-a")
    await _run(sessions, "run-b")
    await repository.open_run("alice", "project", "run-a", 200, 100)
    await repository.open_run("alice", "project", "run-b", 200, 100)

    async def reserve(index: int) -> object:
        try:
            return await repository.reserve_call(
                f"charge-{index}", "alice", "project", "run-a", index, 10, "mock", "mock-model"
            )
        except ProjectBudgetExceeded as exc:
            return exc

    results = await asyncio.gather(*(reserve(index) for index in range(20)))
    assert sum(not isinstance(result, Exception) for result in results) == 10
    summary = await repository.summary(owner_id="alice", project_id="project", run_id="run-a")
    assert summary is not None and summary.project_reserved_nusd == 100

    # Release is legal only before dispatch and returns both reservations.
    charges = await repository.list(owner_id="alice", project_id="project", run_id="run-a")
    released_id, dispatched_id = charges[0].charge_id, charges[1].charge_id
    await repository.release(released_id, "alice", "project", "run-a")
    await repository.mark_dispatched(dispatched_id, "alice", "project", "run-a")
    with pytest.raises(QuoteExceeded):
        await repository.reconcile(dispatched_id, "alice", "project", "run-a", 11, 1, 1)
    over = await repository.get(
        dispatched_id, owner_id="alice", project_id="project", run_id="run-a"
    )
    assert over is not None and over.state is ChargeState.INDETERMINATE

    async with sessions() as session:
        rows = (
            await session.scalars(
                select(ModelChargeRow).where(ModelChargeRow.state == ChargeState.RESERVED.value)
            )
        ).all()
        for row in rows:
            row.updated_at = datetime.now(tz=UTC) - timedelta(days=1)
        await session.commit()
    assert await repository.recover_stale(datetime.now(tz=UTC) - timedelta(hours=1)) == 8
    summary = await repository.summary(owner_id="alice", project_id="project", run_id="run-a")
    assert summary is not None and summary.project_reserved_nusd == 10
    aggregate = await repository.reserve_call(
        "other-run", "alice", "project", "run-b", 0, 90, "mock", "mock-model"
    )
    assert aggregate.should_dispatch
    with pytest.raises(ProjectBudgetExceeded):
        await repository.reserve_call(
            "one-over", "alice", "project", "run-b", 1, 1, "mock", "mock-model"
        )
    assert (
        await repository.get(
            aggregate.charge_id, owner_id="mallory", project_id="project", run_id="run-b"
        )
        is None
    )
    assert not ({"prompt", "usage", "payload"} & set(over.__dataclass_fields__))
    with pytest.raises(ChargeStateConflict):
        await repository.release(dispatched_id, "alice", "project", "run-a")
    await engine.dispose()
