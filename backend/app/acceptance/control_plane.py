"""Self-cleaning PostgreSQL race acceptance for durable budgets and effects."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.runtime.effect_ledger import EffectIdentityInput, bind_effect_identity
from app.services.db_store import EffectRow, ModelChargeRow, ProjectBudgetRow, RunRow
from app.services.effect_ledger import EffectRepository
from app.services.monetary_budget import MonetaryBudgetRepository, ProjectBudgetExceeded


async def _seed_runs(
    sessions: async_sessionmaker[AsyncSession],
    *,
    owner_id: str,
    project_id: str,
    run_ids: tuple[str, ...],
) -> None:
    now = datetime.now(tz=UTC)
    async with sessions() as session, session.begin():
        session.add_all(
            RunRow(
                run_id=run_id,
                user_id=owner_id,
                project_id=project_id,
                conversation_id=run_id,
                correlation_id=run_id,
                provider="mock",
                model="mock-model",
                status="running",
                started_at=now,
            )
            for run_id in run_ids
        )


async def _cleanup(
    sessions: async_sessionmaker[AsyncSession],
    *,
    owner_id: str,
    project_id: str,
    run_ids: tuple[str, ...],
) -> None:
    async with sessions() as session, session.begin():
        await session.execute(delete(ModelChargeRow).where(ModelChargeRow.run_id.in_(run_ids)))
        await session.execute(delete(EffectRow).where(EffectRow.run_id.in_(run_ids)))
        await session.execute(delete(RunRow).where(RunRow.run_id.in_(run_ids)))
        await session.execute(
            delete(ProjectBudgetRow).where(
                ProjectBudgetRow.owner_id == owner_id,
                ProjectBudgetRow.project_id == project_id,
            )
        )


async def run() -> None:
    settings = Settings()
    if not settings.database_url.startswith("postgresql+"):
        raise RuntimeError("control_plane_acceptance_requires_postgresql")

    suffix = uuid.uuid4().hex
    owner_id = f"acceptance-{suffix}"
    project_id = f"acceptance-{suffix}"
    effect_run, budget_run_a, budget_run_b = (str(uuid.uuid4()) for _ in range(3))
    run_ids = (effect_run, budget_run_a, budget_run_b)
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        await _seed_runs(
            sessions,
            owner_id=owner_id,
            project_id=project_id,
            run_ids=run_ids,
        )

        effects = EffectRepository(sessions)
        binding = bind_effect_identity(
            EffectIdentityInput(
                owner_id=owner_id,
                project_id=project_id,
                run_id=effect_run,
                tool_name="acceptance_effect",
                arguments={"sentinel": "bounded"},
                input_schema={"type": "object"},
            ),
            b"archon-control-plane-acceptance-key-32-bytes-minimum",
        )
        reservations = await asyncio.gather(*(effects.reserve(binding) for _ in range(32)))
        effect_winners = sum(item.should_execute for item in reservations)
        if effect_winners != 1:
            raise RuntimeError("effect_reservation_winner_count_invalid")

        budgets = MonetaryBudgetRepository(sessions)
        await budgets.open_run(owner_id, project_id, budget_run_a, 100, 100)
        await budgets.open_run(owner_id, project_id, budget_run_b, 100, 100)

        async def reserve(run_id: str, ordinal: int) -> bool:
            try:
                result = await budgets.reserve_call(
                    f"acceptance_charge_{suffix}_{ordinal}",
                    owner_id,
                    project_id,
                    run_id,
                    0,
                    60,
                    "mock",
                    "mock-model",
                )
                return result.should_dispatch
            except ProjectBudgetExceeded:
                return False

        budget_results = await asyncio.gather(reserve(budget_run_a, 1), reserve(budget_run_b, 2))
        budget_winners = sum(budget_results)
        if budget_winners != 1:
            raise RuntimeError("budget_reservation_winner_count_invalid")

        print(
            "CONTROL_PLANE_POSTGRES=PASS "
            f"effect_winners={effect_winners} budget_winners={budget_winners}"
        )
    finally:
        await _cleanup(
            sessions,
            owner_id=owner_id,
            project_id=project_id,
            run_ids=run_ids,
        )
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
