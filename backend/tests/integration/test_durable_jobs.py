from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from app.config import Settings
from app.main import create_app
from app.services.db_store import Base
from app.services.task_queue import DurableJobQueue, InvalidJob
from app.workers.jobs import JobWorker


def test_migration_12_to_13(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ARCHON_DATABASE_URL", raising=False)
    backend = Path(__file__).parents[2]
    database = tmp_path / "jobs-migration.db"
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database}")
    command.upgrade(config, "20260828_12")
    command.upgrade(config, "20260828_13")
    engine = create_engine(f"sqlite:///{database}")
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {"background_jobs", "delegation_nonce_receipts"}.issubset(tables)
    assert {
        "ck_background_jobs_status",
        "ck_background_jobs_kind",
        "ck_background_jobs_attempts",
        "ck_background_jobs_lease_generation",
        "ck_background_jobs_lease_state",
        "ck_background_jobs_completion_state",
    } <= {item["name"] for item in inspector.get_check_constraints("background_jobs")}
    assert "ck_delegation_key_version" in {
        item["name"] for item in inspector.get_check_constraints("delegation_nonce_receipts")
    }
    engine.dispose()

    command.downgrade(config, "20260828_12")
    downgraded = create_engine(f"sqlite:///{database}")
    assert "background_jobs" not in inspect(downgraded).get_table_names()
    assert "delegation_nonce_receipts" not in inspect(downgraded).get_table_names()
    downgraded.dispose()
    command.upgrade(config, "head")
    restored = create_engine(f"sqlite:///{database}")
    assert {"background_jobs", "delegation_nonce_receipts"}.issubset(
        inspect(restored).get_table_names()
    )
    restored.dispose()


@pytest.fixture
async def queue_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'jobs.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    yield lambda **kwargs: DurableJobQueue(sessions, **kwargs)
    await engine.dispose()


@pytest.mark.integration
async def test_restart_persistence_idempotency_and_owner_scope(queue_factory) -> None:
    first = queue_factory()
    created = await first.create("owner", "project", "echo", {"value": 1}, idempotency_key="once")
    duplicate = await first.create("owner", "project", "echo", {"value": 1}, idempotency_key="once")
    restarted = queue_factory()
    assert duplicate["job_id"] == created["job_id"]
    assert (await restarted.get("owner", "project", created["job_id"])) is not None
    assert await restarted.get("other", "project", created["job_id"]) is None

    concurrent = await asyncio.gather(
        restarted.create("owner", "project", "echo", {"value": 3}, idempotency_key="race"),
        restarted.create("owner", "project", "echo", {"value": 3}, idempotency_key="race"),
    )
    assert concurrent[0]["job_id"] == concurrent[1]["job_id"]
    matching = [
        item
        for item in await restarted.list("owner", project_id="project")
        if item["idempotency_key"] == "race"
    ]
    assert len(matching) == 1


@pytest.mark.integration
async def test_atomic_claim_race_and_worker_success(queue_factory) -> None:
    queue = queue_factory()
    created = await queue.create("owner", "project", "echo", {"value": 1})
    claims = await asyncio.gather(queue.claim("one"), queue.claim("two"))
    assert sum(item is not None for item in claims) == 1
    claimed = next(item for item in claims if item is not None)
    await queue.succeed(claimed, {"ok": True})
    assert (await queue.get("owner", "project", created["job_id"]))["status"] == "succeeded"


@pytest.mark.integration
async def test_lease_recovery_retry_dead_letter_cancel_and_manual_retry(queue_factory) -> None:
    now = [datetime(2026, 1, 1, tzinfo=UTC)]
    queue = queue_factory(lease_seconds=1, base_backoff_seconds=0, clock=lambda: now[0])
    job = await queue.create("owner", "project", "echo", {}, max_attempts=3)
    assert await queue.claim("lost") is not None
    now[0] += timedelta(seconds=2)
    assert await queue.recover_expired() == 1
    claim = await queue.claim("worker")
    assert claim is not None
    await queue.fail(claim, "temporary")
    claim = await queue.claim("worker")
    assert claim is not None
    await queue.fail(claim, "temporary")
    assert (await queue.get("owner", "project", job["job_id"]))["status"] == "dead_letter"
    assert not await queue.retry("owner", "other-project", job["job_id"])
    assert await queue.retry("owner", "project", job["job_id"])
    assert not await queue.cancel("owner", "other-project", job["job_id"])
    assert await queue.cancel("owner", "project", job["job_id"])
    assert (await queue.get("owner", "project", job["job_id"]))["status"] == "cancelled"


@pytest.mark.integration
async def test_worker_and_payload_security(queue_factory) -> None:
    queue = queue_factory()
    with pytest.raises(InvalidJob):
        await queue.create("owner", "project", "shell", {})
    with pytest.raises(InvalidJob):
        await queue.create("owner", "project", "echo", {"token": "secret"})
    with pytest.raises(InvalidJob):
        await queue.create("owner", "project", "echo", {"value": "Bearer abcdefghijklmnop"})
    first = await queue.create("owner", "project", "echo", {"safe": True}, idempotency_key="same")
    with pytest.raises(InvalidJob, match="idempotency key conflicts"):
        await queue.create("owner", "project", "echo", {"safe": False}, idempotency_key="same")
    assert (await queue.get("owner", "project", first["job_id"])) is not None
    assert await queue.cancel("owner", "project", first["job_id"])
    item = await queue.create("owner", "project", "echo", {"safe": True})
    assert await JobWorker(queue, "worker").run_once()
    assert (await queue.get("owner", "project", item["job_id"]))["status"] == "succeeded"

    async def leaking_handler(_job):
        return {"api_key": "supersecretvalue"}

    leaked = await queue.create("owner", "project", "echo", {"safe": True})
    assert await JobWorker(queue, "redactor", {"echo": leaking_handler}).run_once()
    assert (await queue.get("owner", "project", leaked["job_id"]))["result"] == {
        "api_key": "[REDACTED_STRUCTURED_SECRET]"
    }


@pytest.mark.integration
async def test_stale_claim_cannot_complete_after_same_worker_reclaims(queue_factory) -> None:
    now = [datetime(2026, 1, 1, tzinfo=UTC)]
    queue = queue_factory(lease_seconds=1, clock=lambda: now[0])
    created = await queue.create("owner", "project", "echo", {})
    stale = await queue.claim("worker")
    assert stale is not None
    now[0] += timedelta(seconds=2)
    assert await queue.recover_expired() == 1
    current = await queue.claim("worker")
    assert current is not None and current.attempts == stale.attempts + 1
    assert not await queue.succeed(stale, {"stale": True})
    assert await queue.succeed(current, {"ok": True})
    assert (await queue.get("owner", "project", created["job_id"]))["result"] == {"ok": True}


@pytest.mark.integration
async def test_expired_final_attempt_moves_to_dead_letter(queue_factory) -> None:
    now = [datetime(2026, 1, 1, tzinfo=UTC)]
    queue = queue_factory(lease_seconds=1, clock=lambda: now[0])
    created = await queue.create("owner", "project", "echo", {}, max_attempts=1)
    assert await queue.claim("worker") is not None
    now[0] += timedelta(seconds=2)
    assert await queue.recover_expired() == 1
    assert (await queue.get("owner", "project", created["job_id"]))["status"] == "dead_letter"


@pytest.mark.integration
async def test_manual_retry_never_reuses_lease_fence(queue_factory) -> None:
    now = [datetime(2026, 1, 1, tzinfo=UTC)]
    queue = queue_factory(lease_seconds=1, clock=lambda: now[0])
    created = await queue.create("owner", "project", "echo", {}, max_attempts=1)
    stale = await queue.claim("same-worker")
    assert stale is not None
    now[0] += timedelta(seconds=2)
    assert await queue.recover_expired() == 1
    assert await queue.retry("owner", "project", created["job_id"])
    current = await queue.claim("same-worker")
    assert current is not None
    assert current.attempts == stale.attempts == 1
    assert current.lease_generation > stale.lease_generation
    assert not await queue.succeed(stale, {"stale": True})
    assert await queue.succeed(current, {"current": True})


@pytest.mark.integration
async def test_worker_heartbeats_and_cancel_fences_running_handler(queue_factory) -> None:
    queue = queue_factory(lease_seconds=1)

    async def slow(job):
        await asyncio.sleep(1.2)
        return {"job_id": job.job_id}

    first = await queue.create("owner", "project", "echo", {})
    assert await JobWorker(queue, "heartbeat", {"echo": slow}).run_once()
    assert (await queue.get("owner", "project", first["job_id"]))["status"] == "succeeded"

    second = await queue.create("owner", "project", "echo", {})
    running = asyncio.create_task(JobWorker(queue, "cancel", {"echo": slow}).run_once())
    for _ in range(40):
        state = await queue.get("owner", "project", second["job_id"])
        if state and state["status"] == "running":
            break
        await asyncio.sleep(0.01)
    assert await queue.cancel("owner", "project", second["job_id"])
    assert await running
    assert (await queue.get("owner", "project", second["job_id"]))["status"] == "cancelled"


@pytest.mark.integration
async def test_worker_hard_timeout_does_not_wait_for_cancellation_cleanup(queue_factory) -> None:
    queue = queue_factory(lease_seconds=1, base_backoff_seconds=0)

    async def cancellation_delaying(_job):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await asyncio.sleep(0.3)
            return {"late": True}

    created = await queue.create("owner", "project", "echo", {}, max_attempts=1)
    started = time.monotonic()
    assert await JobWorker(
        queue,
        "timeout",
        {"echo": cancellation_delaying},
        handler_timeout_seconds=0.1,
    ).run_once()
    assert time.monotonic() - started < 0.25
    assert (await queue.get("owner", "project", created["job_id"]))["status"] == "dead_letter"
    await asyncio.sleep(0.35)


@pytest.mark.integration
async def test_handler_self_cancellation_does_not_cancel_worker(queue_factory) -> None:
    queue = queue_factory(base_backoff_seconds=0)

    async def self_cancel(_job):
        raise asyncio.CancelledError

    first = await queue.create("owner", "project", "echo", {}, max_attempts=1)
    worker = JobWorker(queue, "worker", {"echo": self_cancel})
    assert await worker.run_once()
    assert (await queue.get("owner", "project", first["job_id"]))["status"] == "dead_letter"

    second = await queue.create("owner", "project", "echo", {})
    worker = JobWorker(queue, "worker")
    assert await worker.run_once()
    assert (await queue.get("owner", "project", second["job_id"]))["status"] == "succeeded"


def _headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post("/api/auth/register", json={"username": username, "password": "secret1"})
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.integration
def test_job_api_is_authenticated_owner_scoped_and_rejects_sensitive_payloads(tmp_path) -> None:
    settings = Settings(
        llm_provider="mock",
        debug=True,
        memory_encryption_enabled=False,
        database_url=f"sqlite+aiosqlite:///{tmp_path / f'{uuid.uuid4().hex}.db'}",
        rate_limit_requests=100,
    )
    with TestClient(create_app(settings)) as client:
        alice = _headers(client, "job-alice")
        bob = _headers(client, "job-bob")
        created = client.post(
            "/api/tasks",
            json={
                "kind": "echo",
                "project_id": "project",
                "payload": {"message": "safe"},
                "idempotency_key": "api-once",
            },
            headers=alice,
        )
        assert created.status_code == 201
        job_id = created.json()["job_id"]
        assert (
            client.get(f"/api/tasks/{job_id}?project_id=project", headers=alice).status_code == 200
        )
        assert client.get(f"/api/tasks/{job_id}?project_id=project", headers=bob).status_code == 404
        assert client.get(f"/api/tasks/{job_id}?project_id=other", headers=alice).status_code == 404
        assert client.get("/api/tasks", headers=bob).json()["items"] == []
        assert (
            client.post(
                "/api/tasks",
                json={"kind": "echo", "payload": {"api_key": "supersecretvalue"}},
                headers=alice,
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/tasks",
                json={"kind": "run_export", "payload": {}},
                headers=alice,
            ).status_code
            == 422
        )

        assert client.post("/api/chat", json={"message": "safe"}, headers=alice).status_code == 200
        run_id = client.get("/api/runs", headers=alice).json()["items"][0]["run_id"]
        export_job = client.post(
            "/api/tasks",
            json={
                "kind": "run_export",
                "project_id": "default",
                "payload": {"run_id": run_id},
            },
            headers=alice,
        )
        assert export_job.status_code == 201
        export_job_id = export_job.json()["job_id"]
        result = None
        for _ in range(40):
            result = client.get(
                f"/api/tasks/{export_job_id}?project_id=default", headers=alice
            ).json()
            if result["status"] == "succeeded":
                break
            time.sleep(0.05)
        assert result is not None and result["status"] == "succeeded"
        export_id = result["result"]["export_id"]
        assert (
            client.get(
                f"/api/runs/{run_id}/exports/{export_id}/download", headers=alice
            ).status_code
            == 200
        )
