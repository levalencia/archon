from __future__ import annotations

import asyncio
import copy
import json
import os
import stat
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import scripts.acceptance_support as acceptance_support
from app.config import Settings
from app.runtime.anthropic import normalize_anthropic_usage
from app.runtime.capabilities import ProviderCapabilities
from app.runtime.models import ModelResponse, TokenUsage, ToolCall
from app.runtime.structured_output import ResponseContract
from scripts.acceptance_support import (
    make_report,
    read_report,
    result,
    run_cli_worker,
    scan_report,
    validate_report,
    write_report,
)
from scripts.embedding_smoke import run_acceptance as run_embedding
from scripts.multimodal_smoke import run_multimodal
from scripts.provider_acceptance import run_acceptance as run_provider

NOW = "2026-08-28T00:00:00Z"


def settings(**overrides: Any) -> Settings:
    values = {
        "llm_provider": "openai",
        "llm_model": "gpt-test",
        "llm_api_key": "unit-test-credential",
        "llm_fallback_providers": "",
        "embedding_provider": "openai",
        "embedding_model": "embed-test",
        "embedding_api_key": "unit-test-credential",
        "embedding_dimensions": 3,
    }
    values.update(overrides)
    return Settings(**values)


class FakeProvider:
    def __init__(
        self, capabilities: ProviderCapabilities, *, malformed: bool = False, delay: float = 0.0
    ) -> None:
        self.capabilities = capabilities
        self.calls = 0
        self.malformed = malformed
        self.delay = delay
        self.closed = False
        self.requests: list[dict[str, Any]] = []

    async def complete(self, messages: Any, tools: Any = (), **kwargs: Any) -> ModelResponse:
        self.requests.append({"tools": tools, "kwargs": kwargs})
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        usage = TokenUsage(5, 2, 1, 0)
        if messages and getattr(messages[0], "images", ()):
            return ModelResponse(content="blue" if self.malformed else "red", usage=usage)
        if tools:
            if self.malformed:
                return ModelResponse(content="not a call", usage=usage)
            return ModelResponse(
                tool_calls=(ToolCall("call-1", "acceptance_probe", {"value": "ok"}),), usage=usage
            )
        return ModelResponse(
            content="not json" if self.malformed else '{"answer":"ok"}', usage=usage
        )

    async def close(self) -> None:
        self.closed = True


class HangingCloseProvider(FakeProvider):
    async def close(self) -> None:
        await asyncio.sleep(1)


class FakeEmbedding:
    def __init__(self, *, malformed: bool = False, delay: float = 0.0) -> None:
        self.malformed = malformed
        self.delay = delay
        self.calls = 0
        self.closed = False

    def validate_configuration(self) -> None:
        return None

    async def embed(self, text: str) -> list[float]:
        del text
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return [1.0, float("nan"), 0.0] if self.malformed else [1.0, 0.5, 0.25]

    async def close(self) -> None:
        self.closed = True


class SequencedEmbedding(FakeEmbedding):
    def __init__(self, vectors: list[list[float]]) -> None:
        super().__init__()
        self.vectors = vectors

    async def embed(self, text: str) -> list[float]:
        del text
        vector = self.vectors[self.calls]
        self.calls += 1
        return vector


@pytest.mark.asyncio
async def test_provider_passes_adapter_contracts_and_report_is_deterministic() -> None:
    provider = FakeProvider(
        ProviderCapabilities(native_tools=True, json_schema=True, cache_usage=True, usage=True)
    )
    report = await run_provider(settings(), execute_live=True, provider=provider, clock=lambda: NOW)
    assert report["status"] == "pass"
    assert report["preflight"]["execution_mode"] == "deterministic"
    assert [item["status"] for item in report["results"]] == ["pass", "pass", "pass"]
    assert provider.calls == 2
    assert isinstance(provider.requests[0]["kwargs"].get("response_contract"), ResponseContract)
    assert not provider.requests[0]["tools"]
    assert provider.requests[1]["tools"][0].name == "acceptance_probe"
    assert provider.closed
    assert "unit-test-credential" not in json.dumps(report)


@pytest.mark.asyncio
async def test_provider_unsupported_capabilities_skip_without_calls() -> None:
    provider = FakeProvider(ProviderCapabilities())
    report = await run_provider(settings(), execute_live=True, provider=provider, clock=lambda: NOW)
    assert report["status"] == "skipped"
    assert provider.calls == 0
    assert all(item["error"]["code"] == "unsupported_capability" for item in report["results"])


@pytest.mark.asyncio
async def test_provider_timeout_and_malformed_responses_are_bounded() -> None:
    delayed = FakeProvider(ProviderCapabilities(native_tools=True, json_schema=True), delay=0.05)
    timed = await run_provider(
        settings(), execute_live=True, provider=delayed, timeout=0.001, clock=lambda: NOW
    )
    assert [item["error"]["code"] for item in timed["results"][:2]] == ["timeout", "timeout"]
    malformed = FakeProvider(
        ProviderCapabilities(native_tools=True, json_schema=True), malformed=True
    )
    broken = await run_provider(
        settings(), execute_live=True, provider=malformed, clock=lambda: NOW
    )
    assert [item["status"] for item in broken["results"][:2]] == ["fail", "fail"]
    assert all(set(item.get("error", {})) <= {"category", "code"} for item in broken["results"])

    hanging = HangingCloseProvider(ProviderCapabilities(json_schema=True))
    cleanup = await run_provider(
        settings(), execute_live=True, provider=hanging, timeout=0.001, clock=lambda: NOW
    )
    assert cleanup["status"] == "fail"
    assert cleanup["results"][-1] == {
        "name": "provider_cleanup",
        "status": "fail",
        "error": {"category": "timeout", "code": "timeout"},
    }


@pytest.mark.asyncio
async def test_default_mode_never_constructs_or_calls_provider() -> None:
    provider = FakeProvider(ProviderCapabilities(native_tools=True, images=True, json_schema=True))
    report = await run_provider(
        settings(), execute_live=False, provider=provider, clock=lambda: NOW
    )
    image_report = await run_multimodal(
        settings(), execute_live=False, provider=provider, clock=lambda: NOW
    )
    assert report["status"] == image_report["status"] == "skipped"
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_multimodal_pass_and_unsupported_skip() -> None:
    capable = FakeProvider(ProviderCapabilities(images=True))
    passed = await run_multimodal(
        settings(), execute_live=True, provider=capable, clock=lambda: NOW
    )
    assert passed["status"] == "pass"
    assert passed["results"][0]["metrics"] == {"images": 1, "width": 1, "height": 1}
    unsupported = FakeProvider(ProviderCapabilities())
    skipped = await run_multimodal(
        settings(), execute_live=True, provider=unsupported, clock=lambda: NOW
    )
    assert skipped["status"] == "skipped"
    assert unsupported.calls == 0
    malformed = await run_multimodal(
        settings(),
        execute_live=True,
        provider=FakeProvider(ProviderCapabilities(images=True), malformed=True),
        clock=lambda: NOW,
    )
    assert malformed["status"] == "fail"
    assert malformed["results"][0]["error"]["code"] == "invalid_image_response"


@pytest.mark.asyncio
async def test_embedding_pass_validates_real_service_flow_and_malformed_vector() -> None:
    service = FakeEmbedding()
    report = await run_embedding(
        settings(), execute_live=True, embedding_service=service, clock=lambda: NOW
    )
    assert report["status"] == "pass"
    assert service.calls == 3  # direct probe, ingestion, query
    assert [item["status"] for item in report["results"]] == ["pass", "pass"]
    assert service.closed

    malformed = await run_embedding(
        settings(),
        execute_live=True,
        embedding_service=FakeEmbedding(malformed=True),
        clock=lambda: NOW,
    )
    assert malformed["status"] == "fail"
    assert malformed["results"][0]["status"] == "fail"
    assert malformed["results"][1]["error"]["code"] == "embedding_prerequisite_failed"

    zero_query = await run_embedding(
        settings(),
        execute_live=True,
        embedding_service=SequencedEmbedding([[1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 0.0]]),
        clock=lambda: NOW,
    )
    assert zero_query["status"] == "fail"
    assert zero_query["results"][1]["status"] == "fail"


@pytest.mark.asyncio
async def test_embedding_timeout_is_sanitized() -> None:
    report = await run_embedding(
        settings(),
        execute_live=True,
        embedding_service=FakeEmbedding(delay=0.05),
        timeout=0.001,
        clock=lambda: NOW,
    )
    assert report["results"][0]["error"] == {"category": "timeout", "code": "timeout"}


def test_report_secret_scanner_and_atomic_owner_only_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    preflight = {
        "execute_live": True,
        "execution_mode": "deterministic",
        "provider": "openai",
        "model": "gpt-test",
        "base_host": "api.openai.com",
        "credential_present": True,
        "fallback_configured": False,
    }
    report = make_report(
        kind="model",
        started_at=NOW,
        finished_at=NOW,
        preflight=preflight,
        results=[
            result("structured_output", "pass", metrics={"schema_valid": True}),
            result("native_tool_call", "pass", metrics={"tool_calls": 1}),
            result("cache_metrics", "pass", metrics={"read_tokens": 0, "write_tokens": 0}),
        ],
    )
    target = tmp_path / "acceptance.json"
    write_report(target, report, secrets=("never-write-this",))
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert json.loads(target.read_text()) == report
    scan_report(target.read_text())
    mixed = make_report(
        kind="model",
        started_at=NOW,
        finished_at=NOW,
        preflight=preflight,
        results=[
            result("structured_output", "pass", metrics={"schema_valid": True}),
            result("native_tool_call", "pass", metrics={"tool_calls": 1}),
            result(
                "cache_metrics",
                "skipped",
                error_code="unsupported_capability",
                error_category="capability",
            ),
        ],
    )
    assert mixed["status"] == "skipped"
    extra = copy.deepcopy(report)
    extra["preflight"]["base_url"] = "example.test"
    with pytest.raises(ValueError, match="preflight"):
        validate_report(extra)
    inconsistent = copy.deepcopy(report)
    inconsistent["status"] = "skipped"
    with pytest.raises(ValueError, match="status"):
        validate_report(inconsistent)
    pass_with_error = copy.deepcopy(report)
    pass_with_error["results"][0]["error"] = {"category": "provider", "code": "failure"}
    with pytest.raises(ValueError, match="result"):
        validate_report(pass_with_error)
    with pytest.raises(ValueError, match="credential"):
        write_report(target, report, secrets=(NOW,))
    with pytest.raises(ValueError, match="secret scan"):
        scan_report('{"authorization":"Bearer abcdefgh"}')
    with pytest.raises(ValueError, match="secret scan"):
        scan_report('{"origin":"https://example.com"}')
    with pytest.raises(ValueError, match="secret scan"):
        scan_report('{"detail":"private=value"}')
    with pytest.raises(ValueError, match="temporary directory"):
        write_report(Path.cwd() / "tracked-report.json", report)
    victim = tmp_path / "victim.txt"
    victim.write_text("keep")
    linked = tmp_path / "linked.json"
    linked.symlink_to(victim)
    with pytest.raises(ValueError, match="symlink"):
        write_report(linked, report)
    assert victim.read_text() == "keep"
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(ValueError, match="invalid report parent"):
        write_report(linked_parent / "report.json", report)
    monkeypatch.setattr(acceptance_support, "MAX_REPORT_BYTES", 10)
    with pytest.raises(ValueError, match="size limit"):
        write_report(target, report)


def test_cli_worker_enforces_hard_wall_clock_timeout(tmp_path: Path) -> None:
    worker = tmp_path / "blocking_worker.py"
    worker.write_text("import time\ntime.sleep(60)\n")
    output = tmp_path / "hard-timeout.json"
    started = time.monotonic()
    code, report = run_cli_worker(
        worker,
        [],
        output=output,
        kind="model",
        execute_live=True,
        operation_timeout=1,
        operation_count=1,
        hard_timeout=0.1,
    )
    assert time.monotonic() - started < 2
    assert code == 1
    assert report == read_report(output)
    assert {item["error"]["code"] for item in report["results"]} == {"hard_timeout"}


def test_preflight_contains_no_url_or_credential() -> None:
    configured = settings(llm_base_url="https://example.test/v1?private=value")
    provider = FakeProvider(ProviderCapabilities())
    report = asyncio.run(
        run_provider(configured, execute_live=False, provider=provider, clock=lambda: NOW)
    )
    encoded = json.dumps(report)
    assert "https://" not in encoded
    assert "private=value" not in encoded
    assert "unit-test-credential" not in encoded
    assert report["preflight"]["base_host"] == "example.test"


def test_anthropic_sdk_usage_allows_optional_null_cache_counters() -> None:
    usage = normalize_anthropic_usage(
        SimpleNamespace(
            input_tokens=10,
            output_tokens=2,
            cache_creation_input_tokens=None,
            cache_read_input_tokens=None,
        )
    )
    assert usage == TokenUsage(10, 2, None, None)


@pytest.mark.skipif(
    os.getenv("ARCHON_RUN_LIVE_ACCEPTANCE") != "1",
    reason="requires explicit live acceptance opt-in",
)
def test_live_acceptance_requires_operator_invocation() -> None:
    pytest.skip("Run the scripts directly with --execute-live and a caller-selected report path")
