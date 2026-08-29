"""Contracts for protected local Compose environment generation."""

from __future__ import annotations

import importlib.util
import os
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]
MODULE_PATH = ROOT / "scripts" / "generate-local-env.py"
SPEC = importlib.util.spec_from_file_location("generate_local_env", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


def _provider_env(tmp_path: Path, **overrides: str) -> Path:
    values = {
        "ARCHON_LLM_PROVIDER": "foundry",
        "ARCHON_LLM_MODEL": "claude-opus-4-6",
        "ARCHON_LLM_API_KEY": "test-provider-key",
        "ARCHON_LLM_BASE_URL": "https://foundry.example.test/anthropic",
        "UNRELATED_SECRET": "must-not-be-imported",
    }
    values.update(overrides)
    path = tmp_path / "provider.env"
    path.write_text("".join(f"{key}={value}\n" for key, value in values.items()))
    path.chmod(0o600)
    return path


def test_default_values_are_mock_and_contain_valid_generated_secrets() -> None:
    values = generator.generate_values()

    assert values["ARCHON_RUNTIME_MODE"] == "mock"
    assert values["ARCHON_LLM_PROVIDER"] == "mock"
    assert values["ARCHON_LLM_MODEL"] == "mock-model"
    assert len(values["POSTGRES_PASSWORD"]) == 64
    assert values["ARCHON_SECRET_KEY"]
    assert values["ARCHON_ENCRYPTION_MASTER_KEY"]
    assert 18_000 <= int(values["ARCHON_LOCAL_PORT"]) < 38_000


def test_live_values_import_only_allowlisted_foundry_configuration(tmp_path: Path) -> None:
    values = generator.generate_values(_provider_env(tmp_path))

    assert values["ARCHON_RUNTIME_MODE"] == "live-foundry"
    assert values["ARCHON_LLM_PROVIDER"] == "foundry"
    assert values["ARCHON_LLM_MODEL"] == "claude-opus-4-6"
    assert values["ARCHON_LLM_API_KEY"] == "test-provider-key"
    assert values["ARCHON_LLM_BASE_URL"].startswith("https://")
    assert "UNRELATED_SECRET" not in values


def test_provider_env_rejects_group_or_world_access(tmp_path: Path) -> None:
    path = _provider_env(tmp_path)
    path.chmod(0o644)

    with pytest.raises(ValueError, match="group/world"):
        generator.read_provider_env(path)


def test_provider_env_rejects_symlink(tmp_path: Path) -> None:
    target = _provider_env(tmp_path)
    link = tmp_path / "provider-link.env"
    link.symlink_to(target)

    with pytest.raises(ValueError, match="symbolic link"):
        generator.read_provider_env(link)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"ARCHON_LLM_PROVIDER": "openai"}, "requires ARCHON_LLM_PROVIDER=foundry"),
        ({"ARCHON_LLM_BASE_URL": "http://foundry.example.test"}, "absolute HTTPS URL"),
        ({"ARCHON_LLM_MODEL": "bad model name"}, "invalid managed live model"),
        ({"ARCHON_LLM_API_KEY": ""}, "missing required keys"),
    ],
)
def test_provider_env_rejects_unsupported_or_incomplete_configuration(
    tmp_path: Path, overrides: dict[str, str], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        generator.read_provider_env(_provider_env(tmp_path, **overrides))


def test_write_env_enforces_owner_only_permissions(tmp_path: Path) -> None:
    output = tmp_path / "generated.env"
    output.touch(mode=0o644)

    generator.write_env(output, {"ARCHON_RUNTIME_MODE": "mock"})

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert output.read_text() == "ARCHON_RUNTIME_MODE=mock\n"
    assert output.stat().st_uid == os.getuid()
