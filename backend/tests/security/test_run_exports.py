"""Security and integrity coverage for run export bundles."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.security.disclosure import DisclosureScanner
from app.services.db_store import RunExportRow, RunShareGrantRow


@pytest.mark.security
def test_disclosure_scanner_redacts_structured_secret_values() -> None:
    result = DisclosureScanner().scan(
        {
            "api_key": "supersecretvalue",
            "nested": {
                "password": "correcthorsebattery",
                "token": "abcdefghijklmnop",
                "token_count": 4,
            },
        }
    )

    assert result.redaction_count == 3
    assert result.value["api_key"] == "[REDACTED_STRUCTURED_SECRET]"
    assert result.value["nested"]["password"] == "[REDACTED_STRUCTURED_SECRET]"
    assert result.value["nested"]["token"] == "[REDACTED_STRUCTURED_SECRET]"
    assert result.value["nested"]["token_count"] == 4
    assert "supersecretvalue" not in json.dumps(result.value)
    rescanned = DisclosureScanner().scan(result.value)
    assert rescanned.redaction_count == 0
    assert rescanned.value == result.value


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        llm_provider="mock",
        debug=True,
        secret_key="export-test-pepper",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'exports.db'}",
    )
    with TestClient(create_app(settings=settings)) as value:
        yield value


def _register(client: TestClient, username: str) -> dict:
    response = client.post("/api/auth/register", json={"username": username, "password": "secret1"})
    assert response.status_code == 201
    return response.json()


def _headers(identity: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {identity['access_token']}"}


@pytest.mark.security
def test_export_owner_isolation_hash_only_grant_and_revocation(client: TestClient) -> None:
    owner = _register(client, "export-owner")
    recipient = _register(client, "export-reader")
    stranger = _register(client, "export-other")
    response = client.post("/api/chat", json={"message": "safe evidence"}, headers=_headers(owner))
    assert response.status_code == 200
    runs = client.get("/api/runs", headers=_headers(owner)).json()["items"]
    run_id = runs[0]["run_id"]

    created = client.post(f"/api/runs/{run_id}/exports", headers=_headers(owner))
    assert created.status_code == 201
    export_id = created.json()["export_id"]
    downloaded = client.get(
        f"/api/runs/{run_id}/exports/{export_id}/download", headers=_headers(owner)
    )
    assert downloaded.status_code == 200
    bundle = downloaded.json()
    assert bundle["manifest"]["schema_version"] == 1
    assert "raw_prompts" in bundle["omissions"]
    assert bundle["context"] is not None
    assert (
        client.get(
            f"/api/runs/{run_id}/exports/{export_id}/download", headers=_headers(stranger)
        ).status_code
        == 404
    )

    grant_response = client.post(
        f"/api/runs/{run_id}/exports/{export_id}/shares",
        json={
            "recipient_user_id": recipient["user_id"],
            "purpose": "audit",
            "expires_in_seconds": 300,
        },
        headers=_headers(owner),
    )
    assert grant_response.status_code == 201
    grant = grant_response.json()
    token = grant.pop("token")
    listed = client.get(
        f"/api/runs/{run_id}/exports/{export_id}/shares", headers=_headers(owner)
    ).json()["items"]
    assert "token" not in listed[0] and "token_hash" not in listed[0]

    async def assert_hash_only() -> None:
        async with client.app.state.conversations.session_factory() as session:
            row = await session.scalar(
                select(RunShareGrantRow).where(RunShareGrantRow.grant_id == grant["grant_id"])
            )
            assert row is not None
            assert row.token_hash != token
            assert row.token_hash == client.app.state.run_exports._token_hash(token)

    asyncio.run(assert_hash_only())
    assert (
        client.post(
            "/api/shares/redeem",
            json={"token": token, "purpose": "support"},
            headers=_headers(recipient),
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/shares/redeem",
            json={"token": token, "purpose": "audit"},
            headers=_headers(stranger),
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/shares/redeem",
            json={"token": token, "purpose": "audit"},
            headers=_headers(recipient),
        ).status_code
        == 200
    )
    assert (
        client.delete(f"/api/shares/{grant['grant_id']}", headers=_headers(owner)).status_code
        == 204
    )
    assert (
        client.post(
            "/api/shares/redeem",
            json={"token": token, "purpose": "audit"},
            headers=_headers(recipient),
        ).status_code
        == 404
    )


@pytest.mark.security
def test_disclosure_rescan_rejects_tampered_export(client: TestClient) -> None:
    owner = _register(client, "tamper-owner")
    client.post("/api/chat", json={"message": "safe"}, headers=_headers(owner))
    run_id = client.get("/api/runs", headers=_headers(owner)).json()["items"][0]["run_id"]
    export_id = client.post(f"/api/runs/{run_id}/exports", headers=_headers(owner)).json()[
        "export_id"
    ]

    async def tamper() -> None:
        async with client.app.state.conversations.session_factory() as session:
            row = await session.scalar(
                select(RunExportRow).where(RunExportRow.export_id == export_id)
            )
            assert row is not None
            bundle = json.loads(row.bundle_json)
            bundle["run"]["answer_summary"] = "api_key=supersecretvalue"
            row.bundle_json = json.dumps(bundle)
            await session.commit()

    asyncio.run(tamper())
    response = client.get(
        f"/api/runs/{run_id}/exports/{export_id}/download", headers=_headers(owner)
    )
    assert response.status_code == 409


@pytest.mark.security
def test_share_expiring_during_disclosure_cannot_be_redeemed(client: TestClient) -> None:
    owner = _register(client, "expiry-owner")
    recipient = _register(client, "expiry-reader")
    assert (
        client.post("/api/chat", json={"message": "safe"}, headers=_headers(owner)).status_code
        == 200
    )
    run_id = client.get("/api/runs", headers=_headers(owner)).json()["items"][0]["run_id"]
    export_id = client.post(f"/api/runs/{run_id}/exports", headers=_headers(owner)).json()[
        "export_id"
    ]
    granted = client.post(
        f"/api/runs/{run_id}/exports/{export_id}/shares",
        json={
            "recipient_user_id": recipient["user_id"],
            "purpose": "audit",
            "expires_in_seconds": 300,
        },
        headers=_headers(owner),
    ).json()

    before_expiry = datetime.now(tz=UTC)
    moments = iter((before_expiry, before_expiry + timedelta(days=1)))
    client.app.state.run_exports._clock = lambda: next(moments)
    response = client.post(
        "/api/shares/redeem",
        json={"token": granted["token"], "purpose": "audit"},
        headers=_headers(recipient),
    )
    assert response.status_code == 404


@pytest.mark.security
@pytest.mark.parametrize("tamper_kind", ["identity", "disclosure_audit"])
def test_manifest_tamper_is_rejected(client: TestClient, tamper_kind: str) -> None:
    owner = _register(client, f"manifest-owner-{tamper_kind}")
    assert (
        client.post("/api/chat", json={"message": "safe"}, headers=_headers(owner)).status_code
        == 200
    )
    run_id = client.get("/api/runs", headers=_headers(owner)).json()["items"][0]["run_id"]
    export_id = client.post(f"/api/runs/{run_id}/exports", headers=_headers(owner)).json()[
        "export_id"
    ]

    async def tamper() -> None:
        async with client.app.state.conversations.session_factory() as session:
            row = await session.scalar(
                select(RunExportRow).where(RunExportRow.export_id == export_id)
            )
            assert row is not None
            bundle = json.loads(row.bundle_json)
            if tamper_kind == "identity":
                bundle["manifest"]["run_id"] = "other-run"
            else:
                bundle["manifest"]["disclosure_scan"]["redaction_count"] = 999
            row.bundle_json = json.dumps(bundle)
            await session.commit()

    asyncio.run(tamper())
    response = client.get(
        f"/api/runs/{run_id}/exports/{export_id}/download", headers=_headers(owner)
    )
    assert response.status_code == 409
