"""Transactional and database-enforced run lineage tests."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.security.persistence_redactor import PersistenceRedactor
from app.services.db_store import DatabaseStore, RunRow
from app.services.run_ledger import RunRepository


async def _parent(repository: RunRepository) -> None:
    await repository.ensure_run(
        run_id="parent",
        user_id="alice",
        project_id="alpha",
        conversation_id="conversation",
        correlation_id="correlation",
        provider="mock",
        model="model",
    )


def _child(repository: RunRepository, run_id: str = "child") -> Coroutine[Any, Any, None]:
    return repository.ensure_child_run(
        run_id=run_id,
        parent_run_id="parent",
        user_id="alice",
        project_id="alpha",
        provider="verifier",
        model="model",
    )


@pytest.mark.asyncio
async def test_child_requires_exact_parent_project_and_creates_nothing_on_rejection(
    tmp_path,
) -> None:
    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path / 'lineage.db'}")
    await store.initialize()
    repository = RunRepository(store.session_factory, PersistenceRedactor())
    await _parent(repository)

    with pytest.raises(ValueError, match="parent run owner mismatch"):
        await repository.ensure_child_run(
            run_id="foreign-project-child",
            parent_run_id="parent",
            user_id="alice",
            project_id="beta",
            provider="verifier",
            model="model",
        )
    async with store.session_factory() as session:
        assert await session.get(RunRow, "foreign-project-child") is None
    await store.close()


@pytest.mark.asyncio
async def test_concurrent_child_ensures_are_idempotent_and_parent_delete_is_restricted(
    tmp_path,
) -> None:
    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path / 'lineage-race.db'}")
    await store.initialize()
    repository = RunRepository(store.session_factory, PersistenceRedactor())
    await _parent(repository)

    results = await asyncio.gather(_child(repository), _child(repository), return_exceptions=True)
    assert not [item for item in results if isinstance(item, BaseException)]
    async with store.session_factory() as session:
        children = tuple(await session.scalars(select(RunRow).where(RunRow.run_id == "child")))
        assert len(children) == 1
        with pytest.raises(IntegrityError):
            await session.execute(delete(RunRow).where(RunRow.run_id == "parent"))
        await session.rollback()
        assert await session.get(RunRow, "parent") is not None

    await store.close()
