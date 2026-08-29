"""Authenticated API coverage for owner/project-scoped encrypted memory."""

from __future__ import annotations

from functools import partial
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.memory.scoped import ScopedEncryptedMemoryRepository


def _register(client: TestClient, username: str) -> tuple[str, dict[str, str]]:
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": "secret-password"},
    )
    assert response.status_code == 201
    body = response.json()
    return body["user_id"], {"Authorization": f"Bearer {body['access_token']}"}


@pytest.fixture
def memory_api(tmp_path: Path):
    database_path = tmp_path / "memory-api.db"
    settings = Settings(
        llm_provider="mock",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{database_path}",
        secret_key="memory-api-test-secret",
    )
    with TestClient(create_app(settings)) as client:
        alice_id, alice_headers = _register(client, "memory-alice")
        bob_id, bob_headers = _register(client, "memory-bob")
        repository: ScopedEncryptedMemoryRepository = client.app.state.scoped_memory
        secrets = {
            "alice_default": "API-ONLY alice default secret",
            "alice_red": "API-ONLY alice red secret",
            "bob_red": "API-ONLY bob red secret",
            "provenance": "API-ONLY provenance secret",
        }
        for owner, project, content in (
            (alice_id, "default", secrets["alice_default"]),
            (alice_id, "red", secrets["alice_red"]),
            (bob_id, "red", secrets["bob_red"]),
        ):
            client.portal.call(
                partial(
                    repository.add,
                    owner,
                    project,
                    content,
                    provenance={"source_action": secrets["provenance"]},
                )
            )
        yield client, database_path, alice_headers, bob_headers, secrets


@pytest.mark.integration
def test_list_export_and_delete_are_bound_to_authenticated_owner_and_requested_project(
    memory_api,
) -> None:
    client, database_path, alice_headers, bob_headers, secrets = memory_api

    listed_red = client.get("/api/memory/facts?project_id=red", headers=alice_headers)
    assert listed_red.status_code == 200
    assert listed_red.json()["project_id"] == "red"
    assert [fact["content"] for fact in listed_red.json()["facts"]] == [secrets["alice_red"]]

    exported_red = client.get("/api/memory/export?project_id=red", headers=alice_headers)
    assert exported_red.status_code == 200
    assert exported_red.json()["project_id"] == "red"
    assert [fact["content"] for fact in exported_red.json()["facts"]] == [secrets["alice_red"]]

    listed_default = client.get("/api/memory/facts", headers=alice_headers)
    assert [fact["content"] for fact in listed_default.json()["facts"]] == [
        secrets["alice_default"]
    ]

    deleted_red = client.delete("/api/memory/facts?project_id=red", headers=alice_headers)
    assert deleted_red.status_code == 200
    assert deleted_red.json() == {"project_id": "red", "deleted": 1}

    assert (
        client.get("/api/memory/facts?project_id=red", headers=alice_headers).json()["facts"] == []
    )
    assert [
        fact["content"]
        for fact in client.get("/api/memory/facts", headers=alice_headers).json()["facts"]
    ] == [secrets["alice_default"]]
    assert [
        fact["content"]
        for fact in client.get("/api/memory/facts?project_id=red", headers=bob_headers).json()[
            "facts"
        ]
    ] == [secrets["bob_red"]]

    raw_database = b"".join(
        path.read_bytes() for path in database_path.parent.glob("memory-api.db*")
    )
    for plaintext in secrets.values():
        assert plaintext.encode() not in raw_database


@pytest.mark.integration
def test_unknown_and_malformed_project_ids_have_explicit_safe_behavior(memory_api) -> None:
    client, _, alice_headers, _, secrets = memory_api

    for path in ("/api/memory/facts", "/api/memory/export"):
        response = client.get(f"{path}?project_id=unknown", headers=alice_headers)
        assert response.status_code == 200
        assert response.json() == {"project_id": "unknown", "facts": []}

    deleted = client.delete("/api/memory/facts?project_id=unknown", headers=alice_headers)
    assert deleted.status_code == 200
    assert deleted.json() == {"project_id": "unknown", "deleted": 0}
    assert [
        fact["content"]
        for fact in client.get("/api/memory/facts", headers=alice_headers).json()["facts"]
    ] == [secrets["alice_default"]]

    for malformed in ("", "bad/project", "contains%20space"):
        response = client.get(f"/api/memory/facts?project_id={malformed}", headers=alice_headers)
        assert response.status_code == 422


@pytest.mark.integration
def test_rotation_status_and_batch_are_owner_project_scoped(memory_api) -> None:
    client, _, alice_headers, bob_headers, secrets = memory_api

    alice = client.get("/api/memory/rotation?project_id=red", headers=alice_headers)
    bob = client.get("/api/memory/rotation?project_id=red", headers=bob_headers)
    assert alice.status_code == bob.status_code == 200
    assert alice.json() == {
        "project_id": "red",
        "active_version": 1,
        "version_counts": {"1": 1},
        "remaining": 0,
        "complete": True,
        "retirement_requires_legacy_writer_drain": True,
    }
    assert bob.json()["version_counts"] == {"1": 1}

    rotated = client.post(
        "/api/memory/rotation?project_id=red",
        headers=alice_headers,
        json={"batch_size": 1},
    )
    assert rotated.status_code == 200
    assert rotated.json()["rotated"] == 0
    serialized = str(rotated.json())
    assert all(secret not in serialized for secret in secrets.values())

    unknown = client.get("/api/memory/rotation?project_id=unknown", headers=alice_headers)
    assert unknown.status_code == 200
    assert unknown.json()["version_counts"] == {}


@pytest.mark.integration
@pytest.mark.parametrize("payload", [{"batch_size": 0}, {"batch_size": 1001}, {"batch_size": True}])
def test_rotation_rejects_invalid_batch_size(memory_api, payload) -> None:
    client, _, alice_headers, _, _ = memory_api
    response = client.post(
        "/api/memory/rotation?project_id=red", headers=alice_headers, json=payload
    )
    assert response.status_code == 422


@pytest.mark.integration
def test_rotation_status_is_rate_limited(memory_api) -> None:
    client, _, alice_headers, _, _ = memory_api
    client.app.state.settings.rate_limit_requests = 1

    assert (
        client.get("/api/memory/rotation?project_id=red", headers=alice_headers).status_code == 200
    )
    limited = client.get("/api/memory/rotation?project_id=red", headers=alice_headers)
    assert limited.status_code == 429
    assert "retry-after" in limited.headers


@pytest.mark.integration
def test_openapi_documents_only_project_id_for_scoped_memory_queries() -> None:
    schema = create_app(Settings(llm_provider="mock", debug=True)).openapi()

    for path, method in (
        ("/api/memory/facts", "get"),
        ("/api/memory/export", "get"),
        ("/api/memory/facts", "delete"),
    ):
        parameters = schema["paths"][path][method]["parameters"]
        project_parameters = [parameter for parameter in parameters if parameter["in"] == "query"]
        assert [parameter["name"] for parameter in project_parameters] == ["project_id"]
        parameter = project_parameters[0]
        assert parameter["description"] == "Memory project scope for this operation."
        assert parameter["schema"]["default"] == "default"
        assert parameter["schema"]["minLength"] == 1
        assert parameter["schema"]["maxLength"] == 100
        assert parameter["schema"]["pattern"] == "^[A-Za-z0-9._-]+$"
