"""Live application security-boundary tests for Sprint 1.6b."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app.agents.mock_llm import MockLLM
from app.config import Settings
from app.main import create_app
from app.runtime.models import Message, ModelResponse, ToolDefinition


@contextmanager
def authenticated_client(
    tmp_path, responses: list[str | ModelResponse], **overrides: object
) -> Iterator[TestClient]:
    from app.routes import chat

    database = tmp_path / f"live-{uuid.uuid4().hex}.db"
    settings = Settings(
        llm_provider="mock",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{database}",
        **overrides,
    )
    chat._llm_singleton = MockLLM(responses)
    try:
        with TestClient(create_app(settings)) as client:
            token = client.post(
                "/api/auth/register",
                json={"username": f"user-{uuid.uuid4().hex}", "password": "secret1"},
            ).json()["access_token"]
            client.headers.update({"Authorization": f"Bearer {token}"})
            client.database_path = database  # type: ignore[attr-defined]
            yield client
    finally:
        chat._llm_singleton = None
        chat._tools_singleton = None


def raw_database_text(path: object) -> str:
    connection = sqlite3.connect(str(path))
    try:
        return "\n".join(
            str(value)
            for table in ("conversations", "messages", "runtime_events", "memory_facts")
            for row in connection.execute(f"SELECT * FROM {table}")  # noqa: S608
            for value in row
        )
    finally:
        connection.close()


@pytest.mark.integration
def test_sync_and_sse_redact_user_assistant_and_artifact_persistence(tmp_path) -> None:
    sync_user_secrets = ("private.user@example.com", "202-555-0147")
    sync_assistant_secrets = ("123-45-6789", "4111-1111-1111-1111")
    sse_user_secrets = ("other.user@example.net", "303-555-0182")
    sse_assistant_secrets = ("987-65-4321", "5555-5555-5555-4444")
    sync_answer = f"answer ssn {sync_assistant_secrets[0]}; card {sync_assistant_secrets[1]}"
    artifact = (
        f"```text\n{'x' * 60} ssn {sse_assistant_secrets[0]}; card {sse_assistant_secrets[1]}\n```"
    )
    with authenticated_client(tmp_path, [sync_answer, artifact]) as client:
        sync_message = "contact " + " ".join(sync_user_secrets)
        stream_message = "contact " + " ".join(sse_user_secrets)
        sync = client.post("/api/chat", json={"message": sync_message})
        stream = client.post("/api/chat/stream", json={"message": stream_message})
        assert sync.status_code == stream.status_code == 200
        assert all(secret in sync.request.content.decode() for secret in sync_user_secrets)
        assert all(secret in sync.json()["response"] for secret in sync_assistant_secrets)
        assert all(secret in stream.text for secret in sse_assistant_secrets)

        raw = raw_database_text(client.database_path)  # type: ignore[attr-defined]
        stored_artifacts = list(client.app.state.artifacts._artifacts.values())

    all_secrets = (
        sync_user_secrets + sync_assistant_secrets + sse_user_secrets + sse_assistant_secrets
    )
    assert all(secret not in raw for secret in all_secrets)
    assert all(tag in raw for tag in ("[EMAIL]", "[PHONE]", "[SSN]", "[CREDIT_CARD]"))
    assert stored_artifacts
    assert all(secret not in item.content for item in stored_artifacts for secret in all_secrets)
    assert any(
        "[SSN]" in item.content and "[CREDIT_CARD]" in item.content for item in stored_artifacts
    )


@pytest.mark.integration
def test_live_rate_limits_are_scoped_by_action_and_skip_health(tmp_path) -> None:
    with authenticated_client(
        tmp_path,
        ["first"],
        rate_limit_requests=1,
        rate_limit_window=60,
    ) as client:
        assert client.post("/api/chat", json={"message": "one"}).status_code == 200
        limited = client.post("/api/chat/stream", json={"message": "two"})
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "60"

        # Approval has a separate action bucket even after chat quota is consumed.
        approval_url = f"/api/chat/approve/{uuid.uuid4()}"
        body = {"approved": True, "run_id": str(uuid.uuid4())}
        assert client.post(approval_url, json=body).status_code == 404
        approval_limited = client.post(approval_url, json=body)
        assert approval_limited.status_code == 429
        assert "retry-after" in approval_limited.headers

        assert client.get("/healthz").status_code == 200
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 200


@pytest.mark.integration
def test_memory_mutation_has_its_own_limited_bucket(tmp_path) -> None:
    with authenticated_client(
        tmp_path,
        ["unused"],
        rate_limit_requests=1,
        memory_encryption_enabled=True,
    ) as client:
        assert client.delete("/api/memory/facts?project_id=one").status_code == 200
        limited = client.delete("/api/memory/facts?project_id=one")
        assert limited.status_code == 429
        assert "retry-after" in limited.headers


@pytest.mark.integration
def test_redis_configuration_fails_startup_when_backend_is_unavailable(
    tmp_path, monkeypatch
) -> None:
    class UnavailableRedis:
        closed = False

        async def ping(self) -> None:
            raise ConnectionError("private redis detail")

        async def aclose(self) -> None:
            self.closed = True

    fake = UnavailableRedis()
    monkeypatch.setattr("redis.asyncio.Redis.from_url", lambda _url: fake)
    settings = Settings(
        llm_provider="mock",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'redis-startup.db'}",
        rate_limit_backend="redis",
    )

    with (
        pytest.raises(RuntimeError, match="Redis rate limiter is unavailable"),
        TestClient(create_app(settings)),
    ):
        pass
    assert fake.closed


@pytest.mark.integration
def test_rate_limit_users_are_isolated(tmp_path) -> None:
    with authenticated_client(tmp_path, ["one", "two"], rate_limit_requests=1) as client:
        first_headers = dict(client.headers)
        assert client.post("/api/chat", json={"message": "one"}).status_code == 200
        assert client.post("/api/chat", json={"message": "blocked"}).status_code == 429

        second = client.post(
            "/api/auth/register",
            json={"username": f"other-{uuid.uuid4().hex}", "password": "secret1"},
            headers={
                key: value for key, value in first_headers.items() if key.lower() != "authorization"
            },
        )
        second_headers = {"Authorization": f"Bearer {second.json()['access_token']}"}
        assert (
            client.post("/api/chat", json={"message": "two"}, headers=second_headers).status_code
            == 200
        )


@pytest.mark.integration
def test_sync_failure_opens_shared_breaker_and_sse_does_not_call_delegate(tmp_path) -> None:
    secret = "provider leaked private.user@example.com"

    class FailingProvider:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(
            self,
            messages: Sequence[Message],
            tools: Sequence[ToolDefinition] = (),
            *,
            max_tokens: int = 4096,
        ) -> ModelResponse:
            del messages, tools, max_tokens
            self.calls += 1
            raise RuntimeError(secret)

    from app.routes import chat

    provider = FailingProvider()
    chat._llm_singleton = provider
    settings = Settings(
        llm_provider="mock",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'breaker.db'}",
        circuit_breaker_failure_threshold=1,
        circuit_breaker_recovery_timeout=60,
    )
    try:
        with TestClient(create_app(settings)) as client:
            token = client.post(
                "/api/auth/register", json={"username": "breaker-user", "password": "secret1"}
            ).json()["access_token"]
            client.headers.update({"Authorization": f"Bearer {token}"})
            sync = client.post("/api/chat", json={"message": "prompt secret"})
            assert sync.status_code == 200
            assert client.app.state.provider_breaker.state.value == "open"
            calls_after_open = provider.calls

            stream = client.post("/api/chat/stream", json={"message": "another prompt secret"})
            readiness = client.get("/readyz")

        assert provider.calls == calls_after_open == 1
        assert secret not in sync.text
        assert secret not in stream.text
        assert "prompt secret" not in stream.text
        assert readiness.status_code == 200
        assert readiness.json()["dependencies"]["model_provider_circuit"] == "open"
    finally:
        chat._llm_singleton = None
