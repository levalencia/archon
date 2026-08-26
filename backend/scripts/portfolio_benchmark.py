#!/usr/bin/env python3
"""Deterministic, offline portfolio benchmark over Archon's production control plane.

This benchmark measures control-plane behavior with scripted local adapters. It does not
measure model quality and never contacts an external model or network service.
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.agents.fallback_chain import FallbackLLMChain  # noqa: E402
from app.runtime import (
    AgentRuntime,
    AuthorizationOutcome,
    AuthorizationRequest,
    Message,
    ModelResponse,
    RecordingEventSink,
    Role,
    StopReason,
    TokenUsage,
    ToolCall,
)
from app.security.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError, CircuitState
from app.security.default_policy import default_policy_engine
from app.security.persistence_redactor import PersistenceRedactor
from app.security.policy import RiskClass
from app.services.chunker import DocumentChunk
from app.services.db_store import DatabaseStore
from app.services.grounded_rag import GroundedDocumentWorkflow
from app.services.run_ledger import RunRepository
from app.tools.registry import SecureToolRegistry

SCHEMA_VERSION = "1.0"
BENCHMARK_KIND = "deterministic-local-control-plane"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SUPPORTED_CLAIM = "Alpha uses Python3"
_UNSUPPORTED_CLAIM = "Alpha uses Python3 and Rust"


def _external_output_path(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if path == _REPO_ROOT or _REPO_ROOT in path.parents:
        raise argparse.ArgumentTypeError("output must be outside the repository")
    return path


def _bounded_iterations(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("iterations must be an integer") from exc
    if not 1 <= parsed <= 100:
        raise argparse.ArgumentTypeError("iterations must be between 1 and 100")
    return parsed


def _git_status() -> list[str]:
    completed = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=_REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.splitlines()


def _status_summary(lines: Sequence[str]) -> dict[str, Any]:
    encoded = "\n".join(lines).encode()
    return {"dirty_entries": len(lines), "sha256": hashlib.sha256(encoded).hexdigest()}


def _latency_summary(values: Sequence[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {"p50": 0.0, "p95": 0.0, "max": 0.0}

    def nearest_rank(percent: float) -> float:
        index = max(0, math.ceil(percent * len(ordered)) - 1)
        return round(ordered[index], 3)

    return {"p50": nearest_rank(0.50), "p95": nearest_rank(0.95), "max": round(ordered[-1], 3)}


def _event_kinds(sink: RecordingEventSink) -> list[str]:
    return [event.kind.value for event in sink.events]


class _ScriptedToolProvider:
    """Emit exactly one native call, then a final response after successful execution."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[Any] = (),
        *,
        max_tokens: int = 4096,
        response_format: str | None = None,
    ) -> ModelResponse:
        del tools, max_tokens, response_format
        self.calls += 1
        if any(message.role is Role.TOOL for message in messages):
            return ModelResponse("probe complete", usage=TokenUsage(4, 2))
        return ModelResponse(
            tool_calls=(ToolCall("write-probe-1", "write_file_probe", {"path": "never-created"}),),
            usage=TokenUsage(6, 2),
        )


class _ExactAuthorizer:
    def __init__(self) -> None:
        self.requests: list[AuthorizationRequest] = []

    async def authorize(self, request: AuthorizationRequest) -> AuthorizationOutcome:
        self.requests.append(request)
        return AuthorizationOutcome(
            True,
            request.tool_call_id,
            request.tool_name,
            request.arguments_hash,
            "benchmark_approved",
        )


async def _runtime_case(*, approved: bool) -> dict[str, Any]:
    handler_calls = 0

    async def no_op_probe(path: str) -> dict[str, Any]:
        nonlocal handler_calls
        del path
        handler_calls += 1
        return {"ok": True}

    registry = SecureToolRegistry()
    registry.register(
        "write_file_probe",
        no_op_probe,
        description="No-op write-class benchmark probe",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        requires_approval=True,
        risk_classes=frozenset({RiskClass.WRITE}),
    )
    provider = _ScriptedToolProvider()
    sink = RecordingEventSink()
    authorizer = _ExactAuthorizer() if approved else None
    result = await AgentRuntime(
        provider,
        registry,
        events=sink,
        policy_engine=default_policy_engine(),
        authorizer=authorizer,
    ).run([Message(Role.USER, "run the registered benchmark probe")])

    policy_decisions = [
        {
            "action": str(event.data.get("action")),
            "matched_rule_id": event.data.get("matched_rule_id"),
            "risk_classes": list(event.data.get("risk_classes", ())),
        }
        for event in sink.events
        if event.kind.value == "policy_decided"
    ]
    approval_required = sum(event.kind.value == "approval_required" for event in sink.events)
    approval_decided = sum(event.kind.value == "approval_decided" for event in sink.events)
    return {
        "stop_reason": result.stop_reason.value,
        "handler_calls": handler_calls,
        "provider_calls": provider.calls,
        "event_kinds": _event_kinds(sink),
        "policy_decisions": policy_decisions,
        "approval_burden": {
            "required": approval_required,
            "decided": approval_decided,
            "authorizer_requests": len(authorizer.requests) if authorizer is not None else 0,
        },
        "tokens": result.usage.total_tokens,
    }


async def _scenario_unsafe_write() -> dict[str, Any]:
    started = time.perf_counter()
    unavailable = await _runtime_case(approved=False)
    approved = await _runtime_case(approved=True)
    invariants = {
        "unavailable_stops_without_execution": unavailable["stop_reason"]
        == StopReason.APPROVAL_UNAVAILABLE.value
        and unavailable["handler_calls"] == 0,
        "approved_completes_exactly_once": approved["stop_reason"] == StopReason.COMPLETED.value
        and approved["handler_calls"] == 1,
        "default_policy_asks_for_write": all(
            decision["action"] == "ask"
            and decision["matched_rule_id"] == "side_effects_require_approval"
            and decision["risk_classes"] == ["write"]
            for case in (unavailable, approved)
            for decision in case["policy_decisions"]
        )
        and all(case["policy_decisions"] for case in (unavailable, approved)),
        "approval_burden_recorded": unavailable["approval_burden"]
        == {"required": 0, "decided": 0, "authorizer_requests": 0}
        and approved["approval_burden"] == {"required": 1, "decided": 1, "authorizer_requests": 1},
    }
    return {
        "passed": all(invariants.values()),
        "latency_ms": (time.perf_counter() - started) * 1000,
        "tokens": unavailable["tokens"] + approved["tokens"],
        "invariants": invariants,
        "observation": {"unavailable": unavailable, "approved": approved},
    }


class _FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class _FailingPrimary:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(
        self, messages: list[dict[str, str]], max_tokens: int = 4096, temperature: float = 0.7
    ) -> str:
        del messages, max_tokens, temperature
        self.calls += 1
        raise RuntimeError("private-provider-detail-must-not-appear")


class _SuccessfulSecondary:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(
        self, messages: list[dict[str, str]], max_tokens: int = 4096, temperature: float = 0.7
    ) -> str:
        del messages, max_tokens, temperature
        self.calls += 1
        return "secondary response"


async def _scenario_provider_resilience() -> dict[str, Any]:
    started = time.perf_counter()
    clock = _FakeClock()
    breaker = CircuitBreaker(
        failure_threshold=1, recovery_timeout=5.0, name="portfolio", clock=clock
    )
    failing_calls = 0

    async def fail() -> Any:
        nonlocal failing_calls
        failing_calls += 1
        raise RuntimeError("private-breaker-detail-must-not-appear")

    first_error = ""
    try:
        await breaker.call(fail)
    except RuntimeError:
        first_error = "provider_request_failed"
    state_after_failure = breaker.state.value
    fail_fast_error = ""
    try:
        await breaker.call(fail)
    except CircuitBreakerOpenError as exc:
        fail_fast_error = str(exc)
    fail_fast_preserved_calls = failing_calls == 1
    clock.value = 5.0
    half_open_state = breaker.state.value
    recovered = await breaker.call(lambda: "recovered")
    final_stats = breaker.get_stats()

    primary = _FailingPrimary()
    secondary = _SuccessfulSecondary()
    chain = FallbackLLMChain([primary, secondary])
    fallback_response = await chain.chat([{"role": "user", "content": "local benchmark"}])
    fallback_stats = chain.get_stats()
    invariants = {
        "breaker_opens_at_threshold": state_after_failure == CircuitState.OPEN.value,
        "breaker_fails_fast": fail_fast_error == "Model provider temporarily unavailable"
        and fail_fast_preserved_calls,
        "breaker_half_open_recovers": half_open_state == CircuitState.HALF_OPEN.value
        and recovered == "recovered"
        and final_stats["state"] == CircuitState.CLOSED.value,
        "fallback_uses_secondary": fallback_response == "secondary response"
        and primary.calls == 1
        and secondary.calls == 1,
        "failure_counts_recorded": fallback_stats["failures"] == {0: 1}
        and final_stats["failure_count"] == 0
        and final_stats["total_calls"] == 2,
        "errors_are_sanitized": first_error == "provider_request_failed"
        and "private" not in fail_fast_error,
    }
    return {
        "passed": all(invariants.values()),
        "latency_ms": (time.perf_counter() - started) * 1000,
        "tokens": 0,
        "invariants": invariants,
        "observation": {
            "breaker_states": [state_after_failure, half_open_state, str(final_stats["state"])],
            "breaker_callable_calls": failing_calls,
            "breaker_total_admitted_calls": final_stats["total_calls"],
            "fallback_response": fallback_response,
            "fallback_failure_counts": {
                str(key): value for key, value in fallback_stats["failures"].items()
            },
            "sanitized_errors": [first_error, fail_fast_error],
        },
    }


class _BenchmarkEmbeddings:
    async def embed(self, text: str) -> list[float]:
        del text
        return [1.0, 0.0]


class _BenchmarkVectors:
    backend = "benchmark"

    def __init__(self) -> None:
        self.search_calls = 0
        self.chunk = DocumentChunk(
            id="chunk-alpha",
            document_id="document-alpha",
            content="Alpha uses Python3.",
            chunk_index=0,
            metadata={"title": "Alpha facts"},
            embedding=[1.0, 0.0],
        )

    async def search(self, query_embedding: list[float], **kwargs: Any) -> list[dict[str, Any]]:
        del query_embedding, kwargs
        self.search_calls += 1
        return [{"chunk": self.chunk, "score": 1.0}]


class _GroundingProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[Any] = (),
        *,
        max_tokens: int = 4096,
        response_format: str | None = None,
    ) -> ModelResponse:
        del messages, tools, max_tokens, response_format
        self.calls += 1
        content = json.dumps(
            {
                "claims": [
                    {"text": _SUPPORTED_CLAIM, "evidence_ids": ["E1"]},
                    {"text": _UNSUPPORTED_CLAIM, "evidence_ids": ["E1"]},
                ]
            },
            separators=(",", ":"),
        )
        return ModelResponse(content, usage=TokenUsage(input_tokens=12, output_tokens=8))


async def _scenario_grounding() -> dict[str, Any]:
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="archon-portfolio-") as directory:
        store = DatabaseStore(f"sqlite+aiosqlite:///{Path(directory) / 'runs.db'}")
        await store.initialize()
        try:
            runs = RunRepository(store.session_factory, PersistenceRedactor())
            vectors = _BenchmarkVectors()
            provider = _GroundingProvider()
            workflow = GroundedDocumentWorkflow(
                vector_store=cast(Any, vectors),
                embedding_service=cast(Any, _BenchmarkEmbeddings()),
                model_provider=provider,
                runs=runs,
                provider="deterministic-local",
                model="scripted-grounding",
                top_k=1,
            )
            result = await workflow.run(
                "What technology does Alpha use?",
                owner_id="portfolio-owner",
                project_id="portfolio-project",
                correlation_id="portfolio-correlation",
                document_id=None,
                document_ids={"document-alpha"},
            )
            persisted = await runs.get("portfolio-owner", result.run_id)
            event_page = await runs.events("portfolio-owner", result.run_id)
        finally:
            await store.close()

    event_kinds = [event.kind for event in event_page.items] if event_page is not None else []
    claims = [str(claim["text"]) for claim in result.claims]
    citation_ids = [str(citation["id"]) for citation in result.citations]
    unsupported = list(result.unsupported)
    invariants = {
        "supported_claim_retained": claims == [_SUPPORTED_CLAIM]
        and result.answer == f"{_SUPPORTED_CLAIM} [E1]",
        "overclaim_excluded": _UNSUPPORTED_CLAIM not in claims
        and _UNSUPPORTED_CLAIM not in result.answer,
        "unsupported_is_exact": unsupported == [_UNSUPPORTED_CLAIM],
        "citation_is_verified": citation_ids == ["E1"] and result.grounded,
        "run_persisted_completed": persisted is not None
        and persisted.status == "completed"
        and persisted.stop_reason == "completed",
        "terminal_events_persisted": event_kinds
        == ["evidence_retrieved", "claim_verified", "grounded_answer", "run_stopped"],
        "provider_usage_recorded": provider.calls == 1
        and result.metrics["provider_calls"] == 1
        and result.metrics["total_tokens"] == 20,
    }
    return {
        "passed": all(invariants.values()),
        "latency_ms": (time.perf_counter() - started) * 1000,
        "tokens": int(result.metrics["total_tokens"]),
        "invariants": invariants,
        "observation": {
            "answer": result.answer,
            "claims": claims,
            "unsupported": unsupported,
            "citation_ids": citation_ids,
            "persisted_status": persisted.status if persisted is not None else None,
            "persisted_stop_reason": persisted.stop_reason if persisted is not None else None,
            "persisted_event_kinds": event_kinds,
            "provider_calls": provider.calls,
            "token_usage": {
                "input": result.metrics["input_tokens"],
                "output": result.metrics["output_tokens"],
                "total": result.metrics["total_tokens"],
            },
        },
    }


_SCENARIOS = (
    ("unsafe_write_approval", _scenario_unsafe_write),
    ("provider_resilience", _scenario_provider_resilience),
    ("grounded_document_workflow", _scenario_grounding),
)


async def run_benchmark(iterations: int) -> dict[str, Any]:
    """Run all scenarios and return a JSON-safe report."""
    if not 1 <= iterations <= 100:
        raise ValueError("iterations must be between 1 and 100")
    git_before = _git_status()
    reports: list[dict[str, Any]] = []
    all_failures: list[dict[str, Any]] = []
    failed_iterations = 0
    total_tokens = 0
    for name, scenario in _SCENARIOS:
        outcomes = [await scenario() for _ in range(iterations)]
        failures = [
            {
                "iteration": index,
                "failed_invariants": [key for key, ok in item["invariants"].items() if not ok],
            }
            for index, item in enumerate(outcomes, 1)
            if not item["passed"]
        ]
        failed_iterations += len(failures)
        all_failures.extend({"scenario": name, **failure} for failure in failures)
        observations_stable = all(
            item["invariants"] == outcomes[0]["invariants"]
            and item["observation"] == outcomes[0]["observation"]
            for item in outcomes[1:]
        )
        if not observations_stable:
            all_failures.append(
                {"scenario": name, "iteration": 0, "failed_invariants": ["observations_stable"]}
            )
        scenario_tokens = sum(int(item["tokens"]) for item in outcomes)
        total_tokens += scenario_tokens
        reports.append(
            {
                "id": name,
                "iterations": iterations,
                "passed_iterations": iterations - len(failures),
                "pass_rate": round((iterations - len(failures)) / iterations, 4),
                "passed": not failures and observations_stable,
                "failures": failures,
                "latency_ms": _latency_summary([float(item["latency_ms"]) for item in outcomes]),
                "tokens": scenario_tokens,
                "invariants": outcomes[0]["invariants"],
                "observation": outcomes[0]["observation"],
                "observations_stable": observations_stable,
            }
        )
    git_after = _git_status()
    passed_iterations = iterations * len(_SCENARIOS) - failed_iterations
    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark_kind": BENCHMARK_KIND,
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "claim_scope": "deterministic mock/control-plane; no production or model-quality claim",
        "environment": {
            "python": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "configuration": {
            "iterations": iterations,
            "external_network": False,
            "external_model": False,
            "estimated_cost_usd": 0,
        },
        "workspace": {
            "before": _status_summary(git_before),
            "after": _status_summary(git_after),
            "workspace_unchanged": git_before == git_after,
        },
        "summary": {
            "passed": not all_failures and git_before == git_after,
            "scenario_iterations": iterations * len(_SCENARIOS),
            "passed_iterations": passed_iterations,
            "pass_rate": round(passed_iterations / (iterations * len(_SCENARIOS)), 4),
            "failures": all_failures,
            "tokens": total_tokens,
            "estimated_cost_usd": 0,
        },
        "scenarios": reports,
    }


def _atomic_json_write(path: Path, report: Mapping[str, Any]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        with suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=_external_output_path, required=True, help="atomic JSON report destination"
    )
    parser.add_argument("--iterations", type=_bounded_iterations, default=10)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = asyncio.run(run_benchmark(args.iterations))
    _atomic_json_write(args.output, report)
    return 0 if report["summary"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
