"""Sprint 2B durable checkpoint, fork lineage, and compare tests."""

# ruff: noqa: E501, E702
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Never

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from app.config import Settings
from app.routes.runs import router
from app.security.auth import get_current_user
from app.security.persistence_redactor import PersistenceRedactor
from app.security.rate_limiter import RateLimiter
from app.services.conversations import ConversationRepository
from app.services.db_store import ForkDraftRow, RunCheckpointRow


class ForbiddenSpy:
    calls = 0

    def __getattr__(self, name: str) -> Never:
        self.calls += 1
        raise AssertionError(f"stored-data API must not access {name}")


async def _event(
    repo: ConversationRepository,
    run: str,
    owner: str,
    conversation: str,
    kind: str,
    iteration: int = 0,
) -> None:
    await repo.append_runtime_event(
        run_id=run,
        user_id=owner,
        project_id="project",
        conversation_id=conversation,
        correlation_id=f"corr-{run}",
        provider="mock",
        model="model",
        kind=kind,
        iteration=iteration,
        data={"reason": "complete"} if kind == "run_stopped" else {},
        input_tokens=3,
        output_tokens=5,
        total_tokens=8,
    )


def _app(repo: ConversationRepository, owner: str) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.conversations = repo
    app.state.settings = Settings(rate_limit_requests=100)
    app.state.rate_limiter = RateLimiter(max_requests=100)
    app.state.model_provider = ForbiddenSpy()
    app.state.tools = ForbiddenSpy()
    app.dependency_overrides[get_current_user] = lambda: {"user_id": owner}
    return app


@pytest.mark.asyncio
async def test_fork_is_durable_owner_scoped_validates_sequence_and_propagates_lineage(
    tmp_path: Path,
) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'fork.db'}"
    repo = ConversationRepository(url, PersistenceRedactor())
    await repo.initialize()
    await repo.create("source-conversation", "Source", "alice")
    await repo.store("source-conversation", "user", "email me at person@example.com", "alice")
    await repo.store("source-conversation", "assistant", "safe answer", "alice")
    await _event(repo, "source-run", "alice", "source-conversation", "run_started")
    await _event(repo, "source-run", "alice", "source-conversation", "run_stopped", 1)
    app = _app(repo, "alice")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.post("/api/runs/source-run/fork", json={"source_sequence": 99})
        ).status_code == 404
        response = await client.post("/api/runs/source-run/fork", json={"source_sequence": 2})
        assert response.status_code == 201
        fork = response.json()
        assert fork["workspace_restoration"] == "none"
        target = fork["target_conversation_id"]
        copied = await repo.retrieve(target, user_id="alice")
        assert "person@example.com" not in str(copied)
    await app.state.rate_limiter.close()
    await repo.close()

    restarted = ConversationRepository(url, PersistenceRedactor())
    await restarted.initialize()
    await _event(restarted, "child-run", "alice", target, "run_started")
    child = await restarted.runs.get("alice", "child-run")
    assert child and child.parent_run_id == "source-run" and child.fork_source_sequence == 2
    foreign = _app(restarted, "bob")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=foreign), base_url="http://test"
    ) as client:
        assert (
            await client.post("/api/runs/source-run/fork", json={"source_sequence": 2})
        ).status_code == 404
    await foreign.state.rate_limiter.close()
    await restarted.close()


@pytest.mark.asyncio
async def test_compare_and_filters_are_read_only_and_owner_scoped(tmp_path: Path) -> None:
    repo = ConversationRepository(
        f"sqlite+aiosqlite:///{tmp_path / 'compare.db'}", PersistenceRedactor()
    )
    await repo.initialize()
    await repo.create("conversation", "Source", "alice")
    for run in ("run-a", "run-b"):
        await _event(repo, run, "alice", "conversation", "run_started")
        await _event(repo, run, "alice", "conversation", "run_stopped", 1)
        await repo.runs.finalize_metadata(
            "alice", run, answer=f"answer {run}", cost_usd=0.01, latency_ms=12
        )
    await repo.create("other", "Other", "bob")
    await _event(repo, "run-c", "bob", "other", "run_started")
    app = _app(repo, "alice")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        listing = await client.get(
            "/api/runs", params={"conversation_id": "conversation", "project_id": "project"}
        )
        assert {r["run_id"] for r in listing.json()["items"]} == {"run-a", "run-b"}
        compared = await client.get("/api/runs/compare", params={"a": "run-a", "b": "run-b"})
        assert compared.status_code == 200
        assert compared.json()["a"]["answer_summary"] == "answer run-a"
        assert (
            await client.get("/api/runs/compare", params={"a": "run-a", "b": "run-c"})
        ).status_code == 404
    assert app.state.model_provider.calls == app.state.tools.calls == 0
    await app.state.rate_limiter.close()
    await repo.close()


@pytest.mark.asyncio
async def test_fork_snapshot_uses_selected_event_cutoff_and_terminal_completion(
    tmp_path: Path,
) -> None:
    repo = ConversationRepository(
        f"sqlite+aiosqlite:///{tmp_path / 'snapshot.db'}", PersistenceRedactor()
    )
    await repo.initialize()
    await repo.create("source", "Source", "alice")
    await repo.store("source", "user", "included before run", "alice")
    await _event(repo, "source-run", "alice", "source", "run_started")
    await repo.store("source", "assistant", "excluded after selected event", "alice")

    nonterminal = await repo.runs.fork("alice", "source-run", 1)
    assert nonterminal is not None
    assert await repo.retrieve(nonterminal["target_conversation_id"], user_id="alice") == [
        {"role": "user", "content": "included before run"}
    ]

    await repo.store("source", "user", "included current user", "alice")
    await repo.store("source", "assistant", "included final assistant", "alice")
    await _event(repo, "source-run", "alice", "source", "run_stopped", 1)
    await repo.store("source", "user", "excluded later message", "alice")

    terminal = await repo.runs.fork("alice", "source-run", 2)
    assert terminal is not None
    copied = await repo.retrieve(terminal["target_conversation_id"], user_id="alice")
    assert [item["content"] for item in copied] == [
        "included before run",
        "excluded after selected event",
        "included current user",
        "included final assistant",
    ]
    await repo.close()


@pytest.mark.asyncio
async def test_repeated_and_concurrent_forks_reuse_checkpoint_but_create_distinct_drafts(
    tmp_path: Path,
) -> None:
    repo = ConversationRepository(
        f"sqlite+aiosqlite:///{tmp_path / 'checkpoint-race.db'}", PersistenceRedactor()
    )
    await repo.initialize()
    await repo.create("source", "Source", "alice")
    await repo.store("source", "user", "question", "alice")
    await _event(repo, "source-run", "alice", "source", "run_started")

    forks = await asyncio.gather(*(repo.runs.fork("alice", "source-run", 1) for _ in range(4)))
    assert all(item is not None for item in forks)
    checkpoint_ids = {item["checkpoint_id"] for item in forks if item is not None}
    target_ids = {item["target_conversation_id"] for item in forks if item is not None}
    assert len(checkpoint_ids) == 1
    assert len(target_ids) == 4
    async with repo._store.session_factory() as session:
        assert await session.scalar(select(func.count(RunCheckpointRow.checkpoint_id))) == 1
    await repo.close()


@pytest.mark.asyncio
async def test_fork_draft_is_consumed_once_by_concurrent_distinct_child_runs(
    tmp_path: Path,
) -> None:
    repo = ConversationRepository(
        f"sqlite+aiosqlite:///{tmp_path / 'lineage-race.db'}", PersistenceRedactor()
    )
    await repo.initialize()
    await repo.create("source", "Source", "alice")
    await _event(repo, "source-run", "alice", "source", "run_started")
    fork = await repo.runs.fork("alice", "source-run", 1)
    assert fork is not None
    target = fork["target_conversation_id"]

    async def ensure(run_id: str) -> None:
        await repo.runs.ensure_run(
            run_id=run_id,
            user_id="alice",
            project_id="project",
            conversation_id=target,
            correlation_id=f"corr-{run_id}",
            provider="mock",
            model="model",
        )

    await asyncio.gather(ensure("child-a"), ensure("child-b"))
    children = [
        await repo.runs.get("alice", "child-a"),
        await repo.runs.get("alice", "child-b"),
    ]
    assert sum(child is not None and child.parent_run_id == "source-run" for child in children) == 1
    await ensure("child-a")
    repeated = await repo.runs.get("alice", "child-a")
    assert repeated is not None
    async with repo._store.session_factory() as session:
        assert await session.scalar(select(func.count(ForkDraftRow.id))) == 0
    await repo.close()
