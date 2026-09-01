from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.skills.catalog import (
    AgentGodModeCatalogProvider,
    ExternalSkillMetadata,
    UnavailableSkillCatalogProvider,
    create_skill_catalog_provider,
)
from app.skills.discovery import DiscoveryResult
from app.tools.skill_discovery import GovernedSkillDiscoveryTools

pytestmark = pytest.mark.unit


def _item(**updates: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "external_id": "godmode.safe-skill",
        "name": "safe-skill",
        "description": "Safe metadata summary",
        "source_url": "https://github.com/example/safe-skill",
        "repository": "example/safe-skill",
        "path": "SKILL.md",
        "revision": "a" * 40,
    }
    value.update(updates)
    return value


def _command(tmp_path: Path, body: str) -> Path:
    command = tmp_path / "catalog-command"
    command.write_text(f"#!/usr/bin/python3\n{body}\n")
    command.chmod(0o700)
    return command


@pytest.mark.asyncio
async def test_command_passes_injection_query_as_one_argv_and_sanitizes_env(tmp_path: Path) -> None:
    command = _command(
        tmp_path,
        "import json, os, sys\n"
        "item = " + repr(_item()) + "\n"
        "item['description'] = json.dumps({'argv': sys.argv[1:], 'home': os.getenv('HOME')})\n"
        "print(json.dumps([item]))",
    )
    provider = AgentGodModeCatalogProvider(allowlisted_root=str(tmp_path), executable=str(command))
    query = "python; touch /tmp/should-not-exist && $(id)"
    result = await provider.search(query, limit=5)
    details = json.loads(result[0].description)
    assert details == {"argv": [query], "home": None}
    assert provider.health_code == "available"


@pytest.mark.asyncio
async def test_command_timeout_kills_process_and_fails_closed(tmp_path: Path) -> None:
    command = _command(tmp_path, "import time\ntime.sleep(5)")
    provider = AgentGodModeCatalogProvider(
        allowlisted_root=str(tmp_path), executable=str(command), timeout_seconds=0.05
    )
    assert await provider.search("query", limit=5) == ()
    assert provider.health_code == "timeout"


@pytest.mark.asyncio
async def test_command_oversize_and_malformed_outputs_fail_closed(tmp_path: Path) -> None:
    oversized = _command(tmp_path, "print('x' * 2048)")
    provider = AgentGodModeCatalogProvider(
        allowlisted_root=str(tmp_path), executable=str(oversized), max_stdout_bytes=1024
    )
    assert await provider.search("query", limit=5) == ()
    assert provider.health_code == "output_too_large"

    malformed = tmp_path / "catalog.json"
    malformed.write_text(json.dumps([_item(content="never load this body")]))
    provider = AgentGodModeCatalogProvider(
        allowlisted_root=str(tmp_path), json_index=str(malformed)
    )
    assert await provider.search("safe", limit=5) == ()
    assert provider.health_code == "malformed_output"


@pytest.mark.asyncio
async def test_json_index_pathname_symlink_swap_reads_retained_descriptor(tmp_path: Path) -> None:
    index = tmp_path / "catalog.json"
    index.write_text(json.dumps([_item()]))
    provider = AgentGodModeCatalogProvider(allowlisted_root=str(tmp_path), json_index=str(index))
    index.rename(tmp_path / "retained.json")
    malicious = tmp_path / "malicious.json"
    malicious.write_text(json.dumps([_item(name="malicious", external_id="evil.swap")]))
    index.symlink_to(malicious)
    result = await provider.search("safe", limit=5)
    assert [item.name for item in result] == ["safe-skill"]


@pytest.mark.asyncio
async def test_executable_pathname_symlink_swap_fails_closed(tmp_path: Path) -> None:
    command = _command(tmp_path, "import json\nprint(json.dumps([" + repr(_item()) + "]))")
    provider = AgentGodModeCatalogProvider(allowlisted_root=str(tmp_path), executable=str(command))
    command.rename(tmp_path / "retained-command")
    marker = tmp_path / "executed"
    malicious = _command(tmp_path, f"from pathlib import Path\nPath({str(marker)!r}).touch()")
    malicious.rename(tmp_path / "malicious-command")
    command.symlink_to(tmp_path / "malicious-command")
    assert await provider.search("safe", limit=5) == ()
    assert provider.health_code == "malformed_output"
    assert not marker.exists()


@pytest.mark.asyncio
async def test_disabled_and_misconfigured_providers_are_safe_noops(tmp_path: Path) -> None:
    disabled = create_skill_catalog_provider(
        enabled=False,
        allowlisted_root="",
        executable="",
        json_index="",
        timeout_seconds=2,
        max_stdout_bytes=65536,
        max_results=50,
    )
    invalid = create_skill_catalog_provider(
        enabled=True,
        allowlisted_root=str(tmp_path),
        executable=str(tmp_path / "missing"),
        json_index="",
        timeout_seconds=2,
        max_stdout_bytes=65536,
        max_results=50,
    )
    assert isinstance(disabled, UnavailableSkillCatalogProvider)
    assert disabled.health_code == "disabled"
    assert invalid.health_code == "misconfigured"
    assert await invalid.search("anything", limit=5) == ()


def test_skill_search_merges_available_external_metadata_and_health_is_redacted(
    tmp_path: Path,
) -> None:
    index = tmp_path / "catalog.json"
    index.write_text(json.dumps([_item()]))
    settings = Settings(
        llm_provider="mock",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'api.db'}",
        skill_catalog_enabled=True,
        skill_catalog_allowlisted_root=str(tmp_path),
        skill_catalog_json_index=str(index),
    )
    app = create_app(settings=settings)
    with TestClient(app) as client:
        auth = client.post(
            "/api/auth/register", json={"username": "catalogadmin", "password": "Test-pass-123!"}
        )
        client.headers.update({"Authorization": f"Bearer {auth.json()['access_token']}"})
        response = client.post("/api/skills/search", json={"query": "safe", "limit": 20})
        assert response.status_code == 200
        external = next(item for item in response.json() if item["external_id"])
        assert external["availability"] == "available"
        assert external["source_label"] == "agent-god-mode"
        assert external["enabled"] is False and external["pinned"] is False
        assert external["risk_classes"] == []
        health = client.get("/readyz").json()["dependencies"]["skill_catalog"]
        assert health == "available"
        serialized_health = json.dumps(health)
        assert str(tmp_path) not in serialized_health
        assert str(index) not in serialized_health


class _DiscoveryService:
    async def discover(self, request: Any) -> DiscoveryResult:
        del request
        return DiscoveryResult(
            candidates=(),
            selected=(),
            rejected=(),
            hidden_ids=(),
            context_cost=0,
            available=(
                ExternalSkillMetadata(
                    external_id="godmode.safe-skill",
                    name="safe-skill",
                    description="Metadata only",
                    source_url="https://github.com/example/safe-skill",
                    repository="example/safe-skill",
                    path="SKILL.md",
                    revision=None,
                ),
            ),
        )


@pytest.mark.asyncio
async def test_discover_capabilities_returns_summary_without_external_prompt_body() -> None:
    tools = GovernedSkillDiscoveryTools(
        _DiscoveryService(),  # type: ignore[arg-type]
        owner_id="alice",
        project_id="project",
        permission_decisions={},
    )
    result = await tools.discover_capabilities("safe")
    serialized = json.dumps(result)
    assert result["selected"] == []
    assert result["available"][0]["status"] == "available"
    assert "content" not in serialized
    assert "instructions" not in serialized
    assert "body" not in serialized
