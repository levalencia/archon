"""Sprint 2B durable checkpoint, fork lineage, and compare tests."""

# ruff: noqa: E501, E702
from __future__ import annotations

from pathlib import Path
from typing import Never

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.routes.runs import router
from app.security.auth import get_current_user
from app.security.persistence_redactor import PersistenceRedactor
from app.security.rate_limiter import RateLimiter
from app.services.conversations import ConversationRepository


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
