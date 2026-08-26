"""Authenticated replay API tests: stored data only, strict owner boundary."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.routes.runs import router
from app.security.auth import get_current_user
from app.security.persistence_redactor import PersistenceRedactor
from app.security.rate_limiter import RateLimiter
from app.services.db_store import DatabaseStore
from app.services.run_ledger import RunRepository


class ForbiddenSpy:
    calls = 0

    def __getattr__(self, name: str):
        self.calls += 1
        raise AssertionError(f"replay must not access {name}")


@pytest.mark.asyncio
async def test_replay_is_owner_scoped_and_never_calls_model_or_tools(tmp_path) -> None:
    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path / 'api-ledger.db'}")
    await store.initialize()
    repository = RunRepository(store.session_factory, PersistenceRedactor())
    common = {
        "project_id": "project",
        "conversation_id": "conversation",
        "correlation_id": "correlation",
        "provider": "mock",
        "model": "model",
        "kind": "run_started",
        "iteration": 0,
        "payload": {},
    }
    await repository.append(run_id="alice-run", user_id="alice", **common)
    await repository.append(run_id="bob-run", user_id="bob", **common)

    app = FastAPI()
    app.include_router(router)
    app.state.conversations = SimpleNamespace(runs=repository)
    app.state.settings = Settings(rate_limit_requests=100)
    app.state.rate_limiter = RateLimiter(max_requests=100)
    app.state.model_provider = ForbiddenSpy()
    app.state.tools = ForbiddenSpy()
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "alice"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        listing = await client.get("/api/runs")
        assert listing.status_code == 200
        assert [item["run_id"] for item in listing.json()["items"]] == ["alice-run"]
        assert (await client.get("/api/runs/alice-run")).status_code == 200
        replay = await client.get("/api/runs/alice-run/events")
        assert [item["sequence"] for item in replay.json()["items"]] == [1]
        assert (await client.get("/api/runs/bob-run")).status_code == 404
        assert (await client.get("/api/runs/bob-run/events")).status_code == 404
    assert app.state.model_provider.calls == 0
    assert app.state.tools.calls == 0
    await app.state.rate_limiter.close()
    await store.close()
