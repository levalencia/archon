"""End-to-end API contracts for durable evaluation of recorded runs."""

from __future__ import annotations

import json
from collections.abc import Sequence
from functools import partial
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.runtime.models import Message, ModelResponse, ToolDefinition
from app.security.rate_limiter import RateLimitResult
from app.services.run_ledger import RunRepository


class ForbiddenModelProvider:
    """A valid app-state provider that records any forbidden live evaluation access."""

    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition] = (),
        *,
        max_tokens: int = 4096,
        response_format: str | None = None,
    ) -> ModelResponse:
        del messages, tools, max_tokens, response_format
        self._calls.append("model")
        raise AssertionError("recorded evaluations must not call a model")


class RejectingRateLimiter:
    async def check(self, identifier: str, max_requests: int | None = None) -> RateLimitResult:
        del identifier
        return RateLimitResult(False, max_requests or 1, max_requests or 1, 0, 7)

    async def close(self) -> None:
        return None


async def _seed_run(
    runs: RunRepository,
    *,
    owner_id: str,
    run_id: str,
    terminal: bool,
    grounded: bool = True,
) -> None:
    common = {
        "run_id": run_id,
        "user_id": owner_id,
        "project_id": "project-a",
        "conversation_id": f"conversation-{run_id}",
        "correlation_id": f"correlation-{run_id}",
        "provider": "recorded",
        "model": "recorded",
        "iteration": 1,
    }
    await runs.append(
        **common,
        kind="run_started",
        payload={"safe": True},
    )
    if not terminal:
        return
    if grounded:
        await runs.append(
            **common,
            kind="evidence_retrieved",
            payload={"evidence_ids": ["evidence-1"], "evidence_count": 1},
        )
    await runs.append(
        **common,
        kind="claim_verified",
        payload={
            "supported_count": 1 if grounded else 0,
            "unsupported_count": 0,
            "cited_evidence_ids": ["evidence-1"] if grounded else [],
        },
    )
    if grounded:
        await runs.append(
            **common,
            kind="grounded_answer",
            payload={
                "supported_count": 1,
                "unsupported_count": 0,
                "citation_ids": ["evidence-1"],
            },
        )
    await runs.append(
        **common,
        kind="run_stopped",
        payload={"reason": "complete", "error": False},
        total_tokens=21,
    )
    await runs.finalize_metadata(
        owner_id,
        run_id,
        answer=(
            "Persisted grounded answer [E1]."
            if grounded
            else "I could not find relevant information to answer your question."
        ),
        cost_usd=0.01,
        latency_ms=12.5,
    )


def _register(api: TestClient, username: str) -> dict[str, Any]:
    response = api.post(
        "/api/auth/register",
        json={"username": username, "password": "valid-password-123"},
    )
    assert response.status_code == 201
    return response.json()


def _request(
    grounded_run_id: str,
    abstention_run_id: str,
    *,
    grounded_case_key: str = "grounded-citation",
) -> dict[str, Any]:
    return {
        "project_id": "project-a",
        "dataset_id": "grounded-v1",
        "threshold": 0.85,
        "items": [
            {"run_id": grounded_run_id, "case_key": grounded_case_key},
            {"run_id": abstention_run_id, "case_key": "safe-abstention"},
        ],
    }


def test_recorded_evaluation_api_persists_and_survives_restart(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'recorded-api.db'}"
    settings = Settings(
        llm_provider="mock",
        debug=True,
        memory_encryption_enabled=False,
        database_url=database_url,
    )
    model_calls: list[str] = []
    app = create_app(
        settings,
        model_provider_factory=lambda _settings: ForbiddenModelProvider(model_calls),
    )
    grounded_run_id = "00000000-0000-4000-8000-000000000101"
    abstention_run_id = "00000000-0000-4000-8000-000000000102"

    with TestClient(app) as api:
        request = _request(grounded_run_id, abstention_run_id)
        assert api.post("/api/evals/runs", json=request).status_code == 401
        owner = _register(api, "evaluation-owner")
        headers = {"Authorization": f"Bearer {owner['access_token']}"}
        assert api.portal is not None
        api.portal.call(
            partial(
                _seed_run,
                app.state.conversations.runs,
                owner_id=owner["user_id"],
                run_id=grounded_run_id,
                terminal=True,
            )
        )
        api.portal.call(
            partial(
                _seed_run,
                app.state.conversations.runs,
                owner_id=owner["user_id"],
                run_id=abstention_run_id,
                terminal=True,
                grounded=False,
            )
        )

        spoofed = {**request, "model_revision": "caller-spoof"}
        assert api.post("/api/evals/runs", headers=headers, json=spoofed).status_code == 422

        created = api.post("/api/evals/runs", headers=headers, json=request)
        assert created.status_code == 201
        first = created.json()
        assert first["status"] == "completed"
        assert first["passed"] is True
        assert first["source_run_ids"] == [grounded_run_id, abstention_run_id]
        assert first["model_revision"] == "recorded"
        assert first["provider_revision"] == "recorded"
        assert first["config_revision"] == "runtime-schema-v1"
        assert [case["case_key"] for case in first["cases"]] == [
            "grounded-citation",
            "safe-abstention",
        ]
        assert [case["source_run_id"] for case in first["cases"]] == [
            grounded_run_id,
            abstention_run_id,
        ]
        assert isinstance(first["created_at"], str)
        assert isinstance(first["completed_at"], str)
        json.dumps(first)  # response datetimes and nested metrics are JSON-safe

        second = api.post("/api/evals/runs", headers=headers, json=request)
        assert second.status_code == 201
        second_id = second.json()["id"]
        first_id = first["id"]

        # The route resolves only app.state.evaluation_service. Poison unrelated live
        # dependencies to prove recorded evaluation does not reach model/tool execution.
        app.state.model_provider = object()
        app.state.sandbox_executor = object()
        third = api.post("/api/evals/runs", headers=headers, json=request)
        assert third.status_code == 201
        assert model_calls == []

    restarted_app = create_app(
        settings,
        model_provider_factory=lambda _settings: ForbiddenModelProvider(model_calls),
    )
    with TestClient(restarted_app) as restarted:
        headers = {"Authorization": f"Bearer {owner['access_token']}"}
        listed = restarted.get("/api/evals?project_id=project-a", headers=headers)
        assert listed.status_code == 200
        assert {item["id"] for item in listed.json()["items"]} >= {first_id, second_id}

        fetched = restarted.get(f"/api/evals/{first_id}", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["source_run_ids"] == [grounded_run_id, abstention_run_id]
        assert len(fetched.json()["cases"]) == 2
        assert isinstance(fetched.json()["created_at"], str)

        compared = restarted.get(f"/api/evals/compare?a={first_id}&b={second_id}", headers=headers)
        assert compared.status_code == 200
        assert compared.json()["a"]["id"] == first_id
        assert compared.json()["b"]["id"] == second_id
        assert model_calls == []


def test_recorded_evaluation_api_scope_conflicts_validation_and_rate_limit(tmp_path) -> None:
    settings = Settings(
        llm_provider="mock",
        debug=True,
        memory_encryption_enabled=False,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'recorded-errors.db'}",
    )
    app = create_app(settings)
    with TestClient(app) as api:
        owner = _register(api, "scope-owner")
        foreign = _register(api, "scope-foreign")
        headers = {"Authorization": f"Bearer {owner['access_token']}"}
        terminal_foreign = "00000000-0000-4000-8000-000000000201"
        nonterminal = "00000000-0000-4000-8000-000000000202"
        missing = "00000000-0000-4000-8000-000000000203"
        valid_abstention = "00000000-0000-4000-8000-000000000204"
        assert api.portal is not None
        api.portal.call(
            partial(
                _seed_run,
                app.state.conversations.runs,
                owner_id=foreign["user_id"],
                run_id=terminal_foreign,
                terminal=True,
            )
        )
        api.portal.call(
            partial(
                _seed_run,
                app.state.conversations.runs,
                owner_id=owner["user_id"],
                run_id=nonterminal,
                terminal=False,
            )
        )
        api.portal.call(
            partial(
                _seed_run,
                app.state.conversations.runs,
                owner_id=owner["user_id"],
                run_id=valid_abstention,
                terminal=True,
                grounded=False,
            )
        )

        foreign_response = api.post(
            "/api/evals/runs",
            headers=headers,
            json=_request(terminal_foreign, valid_abstention),
        )
        assert foreign_response.status_code == 404
        missing_response = api.post(
            "/api/evals/runs", headers=headers, json=_request(missing, valid_abstention)
        )
        assert missing_response.status_code == 404

        conflict = api.post(
            "/api/evals/runs", headers=headers, json=_request(nonterminal, valid_abstention)
        )
        assert conflict.status_code == 409
        assert "completed" in conflict.json()["detail"]

        invalid_mapping = api.post(
            "/api/evals/runs",
            headers=headers,
            json=_request(nonterminal, valid_abstention, grounded_case_key="unknown-case"),
        )
        assert invalid_mapping.status_code == 422
        assert "case key" in invalid_mapping.json()["detail"]

        original_limiter = app.state.rate_limiter
        app.state.rate_limiter = RejectingRateLimiter()
        limited = api.post(
            "/api/evals/runs", headers=headers, json=_request(nonterminal, valid_abstention)
        )
        app.state.rate_limiter = original_limiter
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "7"
        assert limited.json()["detail"]["error"] == "rate_limit_exceeded"
