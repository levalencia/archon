"""Deterministic persistence tests for authentication storage."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.security.auth import AuthRepository
from app.services.db_store import ApiKeyRow, DatabaseStore


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        llm_provider="mock",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{tmp_path}/auth.db",
        secret_key="deterministic-test-secret",
    )


def test_register_login_and_api_key_survive_app_rebuild(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        registered = client.post(
            "/api/auth/register",
            json={"username": "persistent", "password": "secret1", "email": "p@example.com"},
        )
        assert registered.status_code == 201
        user_id = registered.json()["user_id"]
        api_key_response = client.post(
            "/api/auth/api-keys",
            headers={"Authorization": f"Bearer {registered.json()['access_token']}"},
            json={"name": "automation"},
        )
        assert api_key_response.status_code == 200
        api_key = api_key_response.json()["api_key"]

    with TestClient(create_app(settings)) as client:
        logged_in = client.post(
            "/api/auth/login", json={"username": "persistent", "password": "secret1"}
        )
        assert logged_in.status_code == 200
        assert logged_in.json()["user_id"] == user_id
        me = client.get("/api/auth/me", headers={"X-API-Key": api_key})
        assert me.status_code == 200
        assert me.json()["user_id"] == user_id
        assert me.json()["auth_method"] == "api_key"


def test_duplicate_user_and_invalid_token(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        payload = {"username": "duplicate", "password": "secret1"}
        assert client.post("/api/auth/register", json=payload).status_code == 201
        duplicate = client.post("/api/auth/register", json=payload)
        assert duplicate.json() == {"error": "Username 'duplicate' already exists"}
        invalid = client.get("/api/auth/me", headers={"Authorization": "Bearer invalid"})
        assert invalid.status_code == 401


def test_expired_token_is_rejected(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        repository: AuthRepository = client.app.state.auth
        token = repository.create_jwt("user-id", "expired", expires_delta=timedelta(seconds=-1))
        expired = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert expired.status_code == 401


@pytest.mark.asyncio
async def test_database_stores_only_api_key_hash(settings: Settings) -> None:
    store = DatabaseStore(settings.database_url)
    await store.initialize()
    repository = AuthRepository(store, settings.secret_key)
    user = await repository.register_user("hashed-key", "secret1")
    key = await repository.register_api_key("test", user["user_id"])
    async with store._session_factory() as session:
        row = (await session.execute(select(ApiKeyRow))).scalar_one()
        assert row.key_hash != key
        assert key not in row.key_hash
    await store.close()
