"""Authenticated replay API tests: stored data only, strict owner boundary."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.routes.runs import router
from app.runtime.effect_ledger import EffectIdentityInput, bind_effect_identity
from app.security.auth import get_current_user
from app.security.persistence_redactor import PersistenceRedactor
from app.security.rate_limiter import RateLimiter
from app.services.db_store import DatabaseStore
from app.services.effect_ledger import EffectRepository
from app.services.monetary_budget import MonetaryBudgetRepository
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
    await repository.ensure_child_run(
        run_id="alice-child",
        parent_run_id="alice-run",
        user_id="alice",
        project_id="project",
        provider="verifier",
        model="model",
    )
    effect_repository = EffectRepository(store.session_factory)
    binding = bind_effect_identity(
        EffectIdentityInput(
            owner_id="alice",
            project_id="project",
            run_id="alice-run",
            tool_name="send",
            arguments={"value": "private"},
            resources=(),
            input_schema={"type": "object"},
        ),
        b"e" * 32,
    )
    await effect_repository.reserve(binding)
    await effect_repository.mark_indeterminate(binding.effect_id, "dispatch_interrupted")
    await MonetaryBudgetRepository(store.session_factory).open_run(
        "alice", "project", "alice-run", 1_000_000_000, 10_000_000_000
    )

    app = FastAPI()
    app.include_router(router)
    app.state.conversations = SimpleNamespace(
        runs=repository, session_factory=store.session_factory
    )
    app.state.settings = Settings(rate_limit_requests=100)
    app.state.rate_limiter = RateLimiter(max_requests=100)
    app.state.model_provider = ForbiddenSpy()
    app.state.tools = ForbiddenSpy()
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "alice"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        listing = await client.get("/api/runs")
        assert listing.status_code == 200
        assert {item["run_id"] for item in listing.json()["items"]} == {
            "alice-run",
            "alice-child",
        }
        detail = await client.get("/api/runs/alice-run")
        assert detail.status_code == 200
        assert detail.json()["monetary_budget"] == {
            "limit_usd": "1",
            "spent_usd": "0",
            "reserved_usd": "0",
            "remaining_usd": "1",
            "project_limit_usd": "10",
            "project_spent_usd": "0",
            "project_reserved_usd": "0",
        }
        effects = await client.get("/api/runs/alice-run/effects")
        assert effects.status_code == 200
        assert effects.json()["items"][0]["effect_id"] == binding.effect_id
        assert "private" not in effects.text
        reviewed = await client.post(
            f"/api/runs/alice-run/effects/{binding.effect_id}/review",
            json={"disposition": "requires_compensation"},
        )
        assert reviewed.status_code == 200
        assert reviewed.json()["state"] == "indeterminate"
        assert reviewed.json()["review_disposition"] == "requires_compensation"
        assert (
            await client.post(
                f"/api/runs/alice-run/effects/{binding.effect_id}/review",
                json={"disposition": "confirmed_failed"},
            )
        ).status_code == 409
        replay = await client.get("/api/runs/alice-run/events")
        assert [item["sequence"] for item in replay.json()["items"]] == [1]
        children = await client.get("/api/runs/alice-run/children")
        assert children.status_code == 200
        assert [item["run_id"] for item in children.json()["items"]] == ["alice-child"]
        assert children.json()["items"][0]["parent_run_id"] == "alice-run"
        assert (await client.get("/api/runs/bob-run")).status_code == 404
        assert (await client.get("/api/runs/bob-run/events")).status_code == 404
        assert (await client.get("/api/runs/bob-run/effects")).status_code == 404
        assert (
            await client.post(
                f"/api/runs/bob-run/effects/{binding.effect_id}/review",
                json={"disposition": "confirmed_failed"},
            )
        ).status_code == 404
        assert (await client.get("/api/runs/bob-run/children")).status_code == 404
    assert app.state.model_provider.calls == 0
    assert app.state.tools.calls == 0
    await app.state.rate_limiter.close()
    await store.close()
