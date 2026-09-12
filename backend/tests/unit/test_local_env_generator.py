"""Contracts for protected local Compose environment generation."""

from __future__ import annotations

import importlib.util
import json
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
        "COGENTREX_LLM_PROVIDER": "foundry",
        "COGENTREX_LLM_MODEL": "claude-opus-4-6",
        "COGENTREX_LLM_API_KEY": "test-provider-key",
        "COGENTREX_LLM_BASE_URL": "https://foundry.example.test/anthropic",
        "LOGFIRE_TOKEN": "test-logfire-token",
        "LOGFIRE_BASE_URL": "https://logfire-eu.pydantic.dev",
        "UNRELATED_SECRET": "must-not-be-imported",
    }
    values.update(overrides)
    path = tmp_path / "provider.env"
    path.write_text("".join(f"{key}={value}\n" for key, value in values.items()))
    path.chmod(0o600)
    return path


def test_default_values_are_mock_and_contain_valid_generated_secrets() -> None:
    values = generator.generate_values()

    assert values["COGENTREX_RUNTIME_MODE"] == "mock"
    assert values["COGENTREX_LLM_PROVIDER"] == "mock"
    assert values["COGENTREX_LLM_MODEL"] == "mock-model"
    assert len(values["POSTGRES_PASSWORD"]) == 64
    assert values["COGENTREX_SECRET_KEY"]
    assert values["COGENTREX_ENCRYPTION_MASTER_KEY"]
    assert values["COGENTREX_EFFECT_IDENTITY_SECRET"]
    assert values["COGENTREX_DELEGATION_SIGNING_KEY"]
    assert values["COGENTREX_DURABLE_MONETARY_BUDGET_ENABLED"] == "true"
    assert values["COGENTREX_DURABLE_EFFECT_LEDGER_ENABLED"] == "true"
    assert values["COGENTREX_AGENT_DEADLINE_SECONDS"] == "300"
    assert values["COGENTREX_VERIFIER_ENABLED"] == "false"
    assert values["COGENTREX_OTEL_DESTINATIONS"] == "debug"
    assert values["COGENTREX_OTEL_CAPTURE_MESSAGE_CONTENT"] == "false"
    assert values["COGENTREX_LEARNING_MEDIA_ENABLED"] == "false"
    assert 18_000 <= int(values["COGENTREX_LOCAL_PORT"]) < 38_000


def test_valid_external_learning_library_is_enabled(tmp_path: Path) -> None:
    library = tmp_path / "cogentrex-learning-media"
    (library / "published").mkdir(parents=True)
    (library / ".cogentrex-learning-library").write_text(
        "cogentrex.learning-library/v1\n", encoding="utf-8"
    )
    (library / "catalog.json").write_text(
        json.dumps(
            {
                "schema": "cogentrex.learning-library",
                "version": 1,
                "source_commit": "a" * 40,
                "packs": [{"id": "example"}],
            }
        ),
        encoding="utf-8",
    )

    values = generator.generate_values(learning_media_root=library)

    assert values["COGENTREX_LEARNING_MEDIA_ENABLED"] == "true"
    assert values["COGENTREX_LEARNING_MEDIA_HOST_DIR"] == str(library.resolve())


def test_invalid_external_learning_library_fails_closed(tmp_path: Path) -> None:
    library = tmp_path / "cogentrex-learning-media"
    library.mkdir()
    (library / ".cogentrex-learning-library").write_text("wrong\n", encoding="utf-8")
    (library / "catalog.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="learning-media"):
        generator.generate_values(learning_media_root=library)


def test_live_values_import_only_allowlisted_foundry_configuration(tmp_path: Path) -> None:
    values = generator.generate_values(_provider_env(tmp_path))

    assert values["COGENTREX_RUNTIME_MODE"] == "live-foundry"
    assert values["COGENTREX_LLM_PROVIDER"] == "foundry"
    assert values["COGENTREX_LLM_MODEL"] == "claude-opus-4-6"
    assert values["COGENTREX_LLM_API_KEY"] == "test-provider-key"
    assert values["COGENTREX_LLM_BASE_URL"].startswith("https://")
    assert values["LOGFIRE_TOKEN"] == "test-logfire-token"
    assert values["LOGFIRE_BASE_URL"] == "https://logfire-eu.pydantic.dev"
    assert values["COGENTREX_OTEL_DESTINATIONS"] == "logfire"
    assert values["COGENTREX_VERIFIER_ENABLED"] == "true"
    assert values["COGENTREX_VERIFIER_MODEL"] == "claude-opus-4-6"
    assert "UNRELATED_SECRET" not in values


def test_live_values_select_jaeger_and_logfire_and_enable_message_content(
    tmp_path: Path,
) -> None:
    values = generator.generate_values(
        _provider_env(
            tmp_path,
            COGENTREX_OTEL_DESTINATIONS="jaeger,logfire",
            COGENTREX_OTEL_CAPTURE_MESSAGE_CONTENT="true",
        )
    )

    assert values["COGENTREX_OTEL_DESTINATIONS"] == "jaeger,logfire"
    assert values["COGENTREX_OTEL_CAPTURE_MESSAGE_CONTENT"] == "true"
    assert values["COMPOSE_PROFILES"] == "jaeger"


def test_live_values_import_complete_embedding_group(tmp_path: Path) -> None:
    values = generator.generate_values(
        _provider_env(
            tmp_path,
            COGENTREX_EMBEDDING_PROVIDER="foundry",
            COGENTREX_EMBEDDING_MODEL="text-embedding-3-small",
            COGENTREX_EMBEDDING_BASE_URL="https://foundry.example.test/models",
            COGENTREX_EMBEDDING_ALLOWED_HOSTS="foundry.example.test",
            COGENTREX_EMBEDDING_DIMENSIONS="1536",
            COGENTREX_EMBEDDING_API_VERSION="2024-05-01-preview",
        )
    )

    assert values["COGENTREX_EMBEDDING_PROVIDER"] == "foundry"
    assert values["COGENTREX_EMBEDDING_MODEL"] == "text-embedding-3-small"
    assert values["COGENTREX_EMBEDDING_API_KEY"] == "test-provider-key"
    assert values["COGENTREX_EMBEDDING_DIMENSIONS"] == "1536"


def test_live_values_reject_incomplete_embedding_group(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="embedding configuration"):
        generator.generate_values(_provider_env(tmp_path, COGENTREX_EMBEDDING_PROVIDER="foundry"))


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
        ({"COGENTREX_LLM_PROVIDER": "openai"}, "requires COGENTREX_LLM_PROVIDER=foundry"),
        ({"COGENTREX_LLM_BASE_URL": "http://foundry.example.test"}, "absolute HTTPS URL"),
        ({"COGENTREX_LLM_MODEL": "bad model name"}, "invalid managed live model"),
        ({"COGENTREX_LLM_API_KEY": ""}, "missing required keys"),
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

    generator.write_env(output, {"COGENTREX_RUNTIME_MODE": "mock"})

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert output.read_text() == "COGENTREX_RUNTIME_MODE=mock\n"
    assert output.stat().st_uid == os.getuid()
