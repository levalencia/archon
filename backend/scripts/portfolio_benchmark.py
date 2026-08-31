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
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[2]
for import_root in (_BACKEND_ROOT, _REPO_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from sandbox_runner import server as runner_server  # type: ignore[import-not-found]

from app.agents.fallback_chain import FallbackLLMChain  # noqa: E402
from app.delegation.envelope import DelegationEnvelopeService, InvalidDelegationEnvelope
from app.eval.candidates import CandidateConflictError, OptimizationCandidateService
from app.eval.drift import DriftService, DriftThresholds
from app.eval.persistence import EvaluationRepository
from app.memory.keys import MemoryKeyring
from app.memory.scoped import ScopedEncryptedMemoryRepository
from app.reflection.models import ReflectionPolicy
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
from app.runtime.capabilities import ProviderCapabilities
from app.runtime.context import build_effective_context, derive_context_asset_hmac_key
from app.runtime.effect_executor import DurableEffectToolExecutor, EffectRunContext
from app.runtime.monetary_budget import BudgetRunContext, DurableBudgetedProvider, PricingCandidate
from app.security.approval_repository import ApprovalRepository, ApprovalStatus
from app.security.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError, CircuitState
from app.security.default_policy import default_policy_engine
from app.security.persistence_redactor import PersistenceRedactor
from app.security.policy import RiskClass
from app.services.chunker import DocumentChunk
from app.services.db_store import Base, DatabaseStore, RunRow, RunShareGrantRow
from app.services.effect_ledger import EffectRepository
from app.services.grounded_rag import GroundedDocumentWorkflow
from app.services.monetary_budget import ChargeState, MonetaryBudgetRepository
from app.services.run_exports import RunExportService
from app.services.run_ledger import RunRepository
from app.services.task_queue import DurableJobQueue
from app.tools.registry import SecureToolRegistry
from app.tools.sandbox_client import SandboxClientConfig, SandboxRunnerClient

SCHEMA_VERSION = "1.0"
BENCHMARK_KIND = "deterministic-local-control-plane"
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

    capabilities = ProviderCapabilities(native_tools=True)

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
        response_contract: Any = None,
    ) -> ModelResponse:
        del messages, tools, max_tokens, response_format, response_contract
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


class _QueueProvider:
    capabilities = ProviderCapabilities()

    def __init__(self, responses: Sequence[ModelResponse | BaseException]) -> None:
        self.responses = list(responses)
        self.calls = 0

    async def complete(
        self, messages: Sequence[Message], tools: Sequence[Any] = (), **kwargs: Any
    ) -> ModelResponse:
        del messages, tools, kwargs
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _outcome(
    started: float,
    invariants: Mapping[str, bool],
    observation: Mapping[str, Any],
    tokens: int = 0,
) -> dict[str, Any]:
    return {
        "passed": all(invariants.values()),
        "latency_ms": (time.perf_counter() - started) * 1000,
        "tokens": tokens,
        "invariants": dict(invariants),
        "observation": dict(observation),
    }


async def _scenario_reflection() -> dict[str, Any]:
    started = time.perf_counter()
    disabled_provider = _QueueProvider([ModelResponse("uncorrected", usage=TokenUsage(3, 1))])
    disabled = await AgentRuntime(disabled_provider, SecureToolRegistry()).run(
        [Message(Role.USER, "check")]
    )
    enabled_provider = _QueueProvider(
        [
            ModelResponse("uncorrected", usage=TokenUsage(3, 1)),
            ModelResponse(
                '{"verdict":"revise","issue_codes":["factual_error"],'
                '"evidence_refs":["draft:L1"],"confidence":1}',
                usage=TokenUsage(4, 2),
            ),
            ModelResponse("corrected", usage=TokenUsage(3, 1)),
        ]
    )
    enabled = await AgentRuntime(
        enabled_provider,
        SecureToolRegistry(),
        reflection_policy=ReflectionPolicy(
            enabled=True,
            max_cost_usd=Decimal("1"),
            input_cost_per_million_usd=Decimal("1"),
            output_cost_per_million_usd=Decimal("1"),
        ),
        reflection_hash_key=b"r" * 32,
        reflection_hash_scope="benchmark\0project\0run",
    ).run([Message(Role.USER, "check")])
    observation = {
        "disabled": {"answer": disabled.content, "provider_calls": disabled_provider.calls},
        "enabled": {"answer": enabled.content, "provider_calls": enabled_provider.calls},
    }
    invariants = {
        "disabled_has_no_reflection_calls": disabled_provider.calls == 1
        and disabled.content == "uncorrected",
        "enabled_revises_once": enabled_provider.calls == 3 and enabled.content == "corrected",
        "enabled_usage_accounts_all_calls": enabled.usage.total_tokens >= 14,
    }
    return _outcome(
        started,
        invariants,
        observation,
        disabled.usage.total_tokens + enabled.usage.total_tokens,
    )


async def _scenario_duplicate_effect() -> dict[str, Any]:
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="archon-effects-") as directory:
        engine = create_async_engine(f"sqlite+aiosqlite:///{Path(directory) / 'effects.db'}")
        sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        calls = 0

        async def write(value: str) -> dict[str, str]:
            nonlocal calls
            calls += 1
            return {"written": value}

        registry = SecureToolRegistry()
        registry.register(
            "write",
            write,
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            risk_classes=frozenset({RiskClass.WRITE}),
        )
        repository = EffectRepository(sessions)
        executor = DurableEffectToolExecutor(
            registry,
            repository,
            EffectRunContext("owner", "project", "run"),
            b"e" * 32,
        )
        first = await executor.execute(ToolCall("first", "write", {"value": "same"}))
        replay = await executor.execute(ToolCall("replay", "write", {"value": "same"}))
        records = await repository.list(owner_id="owner", project_id="project", run_id="run")
        await engine.dispose()
    observation = {
        "handler_calls": calls,
        "first_status": first["written"],
        "replay_status": replay["status"],
        "ledger_state": records[0].state.value,
    }
    invariants = {
        "effect_executes_once": calls == 1,
        "replay_is_blocked": replay["status"] == "duplicate_effect_blocked",
        "one_committed_record": len(records) == 1 and records[0].state.value == "committed",
    }
    return _outcome(started, invariants, observation)


async def _scenario_budget_failure() -> dict[str, Any]:
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="archon-budget-") as directory:
        store = DatabaseStore(f"sqlite+aiosqlite:///{Path(directory) / 'budget.db'}")
        await store.initialize()
        runs = RunRepository(store.session_factory, PersistenceRedactor())
        await runs.ensure_run(
            run_id="run",
            user_id="owner",
            project_id="project",
            conversation_id="conversation",
            correlation_id="correlation",
            provider="openai",
            model="gpt-4o",
        )
        repository = MonetaryBudgetRepository(store.session_factory)
        provider_failure = RuntimeError("raw-provider-secret")
        provider = _QueueProvider([provider_failure])
        wrapped = DurableBudgetedProvider(
            provider,
            repository,
            BudgetRunContext("owner", "project", "run"),
            run_limit_nusd=1_000_000_000,
            project_limit_nusd=1_000_000_000,
            max_input_tokens=1_000,
            pricing_candidates=(PricingCandidate("openai", "gpt-4o"),),
        )
        propagated_by_identity = False
        try:
            await wrapped.complete([Message(Role.USER, "private input")], max_tokens=10)
        except RuntimeError as exc:
            propagated_by_identity = exc is provider_failure
        charges = await repository.list(owner_id="owner", project_id="project", run_id="run")
        await store.close()
    observation = {
        "provider_calls": provider.calls,
        "charge_count": len(charges),
        "charge_state": charges[0].state.value,
        "provider_failure_propagated": propagated_by_identity,
        "reserved_positive": charges[0].reserved_nusd > 0,
    }
    invariants = {
        "reservation_precedes_dispatch": len(charges) == 1 and charges[0].reserved_nusd > 0,
        "failure_is_indeterminate": charges[0].state is ChargeState.INDETERMINATE,
        "provider_failure_propagates_after_reconciliation": propagated_by_identity,
    }
    return _outcome(started, invariants, observation)


class _ContextMemory:
    async def retrieve_with_metadata(
        self, conversation_id: str, limit: int = 20, user_id: str = "default"
    ) -> list[dict[str, Any]]:
        del conversation_id, limit, user_id
        return [{"id": 7, "role": "user", "content": "historical private value"}]


class _NoListedTools:
    def list_tools(self) -> list[Any]:
        return []


async def _scenario_context_rotation() -> dict[str, Any]:
    started = time.perf_counter()
    context = await build_effective_context(
        "current private value",
        "conversation",
        _ContextMemory(),
        _NoListedTools(),
        user_id="owner",
        project_id="project",
        run_id="run",
        memory_ids=("memory-1",),
        skill_ids=("skill-1",),
        images=["data:image/png;base64,AAAA"],
        asset_hmac_key=derive_context_asset_hmac_key("benchmark-secret"),
    )
    with tempfile.TemporaryDirectory(prefix="archon-rotation-") as directory:
        store = DatabaseStore(f"sqlite+aiosqlite:///{Path(directory) / 'rotation.db'}")
        await store.initialize()
        legacy = ScopedEncryptedMemoryRepository(
            store.session_factory,
            MemoryKeyring(1, {1: b"1" * 32}),
            redactor=PersistenceRedactor(),
        )
        await legacy.activate_key_version()
        await legacy.add("owner", "project", "first", provenance={"source_run_id": "run"})
        await legacy.add("owner", "project", "second", provenance={"source_run_id": "run"})
        rotating = ScopedEncryptedMemoryRepository(
            store.session_factory,
            MemoryKeyring(2, {1: b"1" * 32, 2: b"2" * 32}),
            redactor=PersistenceRedactor(),
        )
        await rotating.activate_key_version()
        original = rotating._encrypt
        calls = 0

        def interrupt(**kwargs: Any) -> bytes:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("rotation_interrupted")
            return original(**kwargs)

        rotating._encrypt = interrupt  # type: ignore[method-assign]
        with suppress(RuntimeError):
            await rotating.rotate_batch("owner", "project", batch_size=2)
        rolled_back = await rotating.key_version_counts("owner", "project")
        rotating._encrypt = original  # type: ignore[method-assign]
        resumed = await rotating.rotate_batch("owner", "project", batch_size=2)
        contents = [item.content for item in await rotating.list("owner", "project")]
        await store.close()
    semantic = json.dumps(context.manifest.semantic_document(), sort_keys=True)
    observation = {
        "selected_message_ids": list(context.manifest.selected_message_ids),
        "memory_ids": list(context.manifest.memory_ids),
        "skill_ids": list(context.manifest.skill_ids),
        "asset_fingerprint_count": len(context.manifest.input_asset_fingerprints),
        "versions_after_interruption": {str(key): value for key, value in rolled_back.items()},
        "versions_after_resume": {str(key): value for key, value in resumed.version_counts.items()},
        "recovered_items": contents,
    }
    invariants = {
        "provenance_is_metadata_only": "private value" not in semantic
        and context.manifest.selected_message_ids == (7,),
        "asset_is_keyed_fingerprint": len(context.manifest.input_asset_fingerprints) == 1
        and "AAAA" not in semantic,
        "interruption_rolls_back": rolled_back == {1: 2},
        "rotation_resumes_without_loss": resumed.complete
        and resumed.version_counts == {2: 2}
        and contents == ["first", "second"],
    }
    return _outcome(started, invariants, observation)


async def _scenario_share_grants() -> dict[str, Any]:
    started = time.perf_counter()
    now = [datetime(2026, 1, 1, tzinfo=UTC)]
    with tempfile.TemporaryDirectory(prefix="archon-share-") as directory:
        store = DatabaseStore(f"sqlite+aiosqlite:///{Path(directory) / 'share.db'}")
        await store.initialize()
        runs = RunRepository(store.session_factory, PersistenceRedactor())
        await runs.ensure_run(
            run_id="run",
            user_id="owner",
            project_id="project",
            conversation_id="conversation",
            correlation_id="correlation",
            provider="mock",
            model="mock",
        )
        seeded_secret = "Bearer benchmark-sensitive-token-123456"
        async with store.session_factory() as session:
            await session.execute(
                update(RunRow).where(RunRow.run_id == "run").values(answer_summary=seeded_secret)
            )
            await session.commit()
        service = RunExportService(
            store.session_factory, runs, token_pepper="benchmark-pepper", clock=lambda: now[0]
        )
        exported = await service.create_export("owner", "run")
        assert exported is not None
        first = await service.create_grant("owner", exported.export_id, "reader", "audit", 60)
        assert first is not None
        grant, token = first
        redeemed = await service.redeem("reader", token, "audit")
        revoked = await service.revoke("owner", grant.grant_id)
        after_revoke = await service.redeem("reader", token, "audit")
        second = await service.create_grant("owner", exported.export_id, "reader", "audit", 60)
        assert second is not None
        expiring, expiring_token = second
        now[0] += timedelta(seconds=61)
        after_expiry = await service.redeem("reader", expiring_token, "audit")
        async with store.session_factory() as session:
            rows = (await session.scalars(select(RunShareGrantRow))).all()
        await store.close()
    observation = {
        "initial_redeem": redeemed is not None,
        "revoked": revoked,
        "redeem_after_revoke": after_revoke is not None,
        "redeem_after_expiry": after_expiry is not None,
        "stored_hashes": len(rows),
        "disclosure_redactions": redeemed["manifest"]["disclosure_scan"]["redaction_count"]
        if redeemed
        else 0,
        "seeded_secret_absent": redeemed is not None
        and seeded_secret not in json.dumps(redeemed, sort_keys=True),
    }
    invariants = {
        "valid_grant_is_readable": redeemed is not None,
        "revocation_is_immediate": revoked and after_revoke is None,
        "expiry_is_enforced": expiring.expires_at < now[0] and after_expiry is None,
        "tokens_are_hash_only": all(row.token_hash not in {token, expiring_token} for row in rows),
        "export_disclosure_scanner_redacts_seeded_secret": redeemed is not None
        and redeemed["manifest"]["disclosure_scan"]["redaction_count"] > 0
        and seeded_secret not in json.dumps(redeemed, sort_keys=True),
    }
    return _outcome(started, invariants, observation)


async def _scenario_child_envelope() -> dict[str, Any]:
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="archon-envelope-") as directory:
        engine = create_async_engine(f"sqlite+aiosqlite:///{Path(directory) / 'envelope.db'}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        service = DelegationEnvelopeService(
            sessions, {1: b"a" * 32}, active_key_version=1, max_age_seconds=60
        )
        envelope = service.issue(
            parent_run_id="parent",
            child_run_id="child",
            owner_id="owner",
            project_id="project",
            context_hash="a" * 64,
            budget={"input_tokens": 10, "output_tokens": 5},
            now=1000,
            nonce="benchmark-nonce",
        )

        async def consume(value: Any) -> None:
            await service.verify_and_consume(
                value,
                owner_id="owner",
                project_id="project",
                parent_run_id="parent",
                child_run_id="child",
                context_hash="a" * 64,
                now=1000,
            )

        await consume(envelope)
        replay_blocked = tamper_blocked = False
        try:
            await consume(envelope)
        except InvalidDelegationEnvelope:
            replay_blocked = True
        try:
            await consume(replace(envelope, signature="x" * 43))
        except InvalidDelegationEnvelope:
            tamper_blocked = True
        await engine.dispose()
    observation = {
        "key_version": envelope.key_version,
        "first_consumed": True,
        "replay_blocked": replay_blocked,
        "tamper_blocked": tamper_blocked,
    }
    invariants = {
        "signed_envelope_consumes_once": replay_blocked,
        "signature_is_bound": tamper_blocked,
        "budget_is_bounded_metadata": dict(envelope.budget)
        == {"input_tokens": 10, "output_tokens": 5},
    }
    return _outcome(started, invariants, observation)


async def _scenario_durable_job() -> dict[str, Any]:
    started = time.perf_counter()
    now = [datetime(2026, 1, 1, tzinfo=UTC)]
    with tempfile.TemporaryDirectory(prefix="archon-job-") as directory:
        engine = create_async_engine(f"sqlite+aiosqlite:///{Path(directory) / 'jobs.db'}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        first = DurableJobQueue(
            sessions, lease_seconds=1, base_backoff_seconds=0, clock=lambda: now[0]
        )
        created = await first.create(
            "owner", "project", "echo", {"value": 1}, idempotency_key="once"
        )
        stale = await first.claim("worker")
        assert stale is not None
        restarted = DurableJobQueue(
            sessions, lease_seconds=1, base_backoff_seconds=0, clock=lambda: now[0]
        )
        persisted = await restarted.get("owner", "project", created["job_id"])
        now[0] += timedelta(seconds=2)
        recovered = await restarted.recover_expired()
        current = await restarted.claim("worker")
        assert current is not None
        stale_result = await restarted.succeed(stale, {"stale": True})
        current_result = await restarted.succeed(current, {"ok": True})
        final = await restarted.get("owner", "project", created["job_id"])
        await engine.dispose()
    observation = {
        "persisted_status": persisted["status"] if persisted else None,
        "recovered": recovered,
        "lease_generations": [stale.lease_generation, current.lease_generation],
        "stale_completion": stale_result,
        "current_completion": current_result,
        "final_status": final["status"] if final else None,
    }
    invariants = {
        "job_survives_restart": persisted is not None and persisted["status"] == "running",
        "expired_lease_is_recovered": recovered == 1
        and current.lease_generation > stale.lease_generation,
        "stale_lease_is_fenced": not stale_result and current_result,
        "current_lease_completes": final is not None
        and final["status"] == "succeeded"
        and final["result"] == {"ok": True},
    }
    return _outcome(started, invariants, observation)


async def _scenario_sandbox_breakout() -> dict[str, Any]:
    started = time.perf_counter()
    linux_seccomp = sys.platform == "linux"
    socket_blocked = unlink_blocked = volume_blocked = chmod_blocked = False
    protected_preserved = payload_absent = False
    with tempfile.TemporaryDirectory(prefix="archon-sandbox-") as directory:
        work_dir = Path(directory)
        previous_work_dir = runner_server.WORK_DIR
        previous_python = runner_server.COMMANDS.get("python")
        try:
            runner_server.WORK_DIR = work_dir
            runner_server.COMMANDS["python"] = (sys.executable, "-I", "-")
            if linux_seccomp:
                protected = work_dir / "protected.sock"
                protected.write_text("control")
                control_dir = work_dir / "control"
                control_dir.mkdir(mode=0o550)
                result = await runner_server.execute(
                    {
                        "version": 1,
                        "operation": "execute",
                        "request_id": "2" * 32,
                        "kind": "python",
                        "content": (
                            "import os,socket\n"
                            "try: socket.socket(); raise SystemExit('socket-open')\n"
                            "except OSError: print('socket-blocked')\n"
                            f"try: os.unlink({str(protected)!r}); "
                            "raise SystemExit('unlink-worked')\n"
                            "except OSError: print('unlink-blocked')\n"
                            f"try: open({str(control_dir / 'payload')!r},'wb').write(b'x'); "
                            "raise SystemExit('volume-write')\n"
                            "except OSError: print('volume-blocked')\n"
                            f"try: os.chmod({str(control_dir)!r},0o770); "
                            "raise SystemExit('chmod-worked')\n"
                            "except OSError: print('chmod-blocked')"
                        ),
                        "timeout_seconds": 1.0,
                        "output_bytes": 1024,
                    }
                )
                output = result["stdout"].splitlines()
                socket_blocked = "socket-blocked" in output
                unlink_blocked = "unlink-blocked" in output
                volume_blocked = "volume-blocked" in output
                chmod_blocked = "chmod-blocked" in output
                protected_preserved = protected.exists()
                payload_absent = not (control_dir / "payload").exists()
        finally:
            runner_server.WORK_DIR = previous_work_dir
            if previous_python is None:
                runner_server.COMMANDS.pop("python", None)
            else:
                runner_server.COMMANDS["python"] = previous_python

        missing = SandboxRunnerClient(SandboxClientConfig(str(work_dir / "missing.sock"), 1, 1024))
        no_host_fallback = False
        try:
            await missing.execute("print('must not run')", kind="python")
        except RuntimeError:
            no_host_fallback = True
    seccomp_breakout_blocked = all(
        (
            socket_blocked,
            unlink_blocked,
            volume_blocked,
            chmod_blocked,
            protected_preserved,
            payload_absent,
        )
    )
    observation = {
        "seccomp_platform_supported": linux_seccomp,
        "seccomp_probe_executed": linux_seccomp,
        "socket_blocked": socket_blocked,
        "control_unlink_blocked": unlink_blocked,
        "volume_write_blocked": volume_blocked,
        "control_chmod_blocked": chmod_blocked,
        "protected_control_preserved": protected_preserved,
        "payload_absent": payload_absent,
        "missing_runner_failed_closed": no_host_fallback,
        "transport": "unix_socket",
    }
    invariants = {
        "linux_runner_blocks_breakout_syscalls": seccomp_breakout_blocked
        if linux_seccomp
        else True,
        "non_linux_does_not_claim_seccomp_execution": linux_seccomp
        or not any((socket_blocked, unlink_blocked, volume_blocked, chmod_blocked)),
        "client_has_no_host_fallback": no_host_fallback,
    }
    return _outcome(started, invariants, observation)


async def _scenario_drift_approval() -> dict[str, Any]:
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="archon-candidate-") as directory:
        store = DatabaseStore(f"sqlite+aiosqlite:///{Path(directory) / 'candidate.db'}")
        await store.initialize()
        evaluations = EvaluationRepository(store.session_factory)
        ids = []
        for suffix in ("baseline", "candidate"):
            item = await evaluations.create(
                "owner",
                project_id="project",
                dataset_id="fixture",
                dataset_version="v1",
                dataset_hash=("a" if suffix == "baseline" else "b") * 64,
                source_run_ids=(f"run-{suffix}",),
                threshold=0.8,
                model_revision=f"model-{suffix}",
                provider_revision="provider-v1",
                config_revision=f"config-{suffix}",
            )
            for index in range(2):
                baseline = suffix == "baseline"
                await evaluations.append_case(
                    "owner",
                    item.id,
                    source_run_id=f"run-{suffix}",
                    case_key=f"case-{index}",
                    passed=baseline,
                    score=0.9 if baseline else 0.5,
                    metrics={
                        "latency_ms": 10 if baseline else 20,
                        "total_tokens": 10 if baseline else 20,
                        "cost_usd": 0.01 if baseline else 0.02,
                        "abstained": 0 if baseline else 1,
                        "citation_rate": 1.0 if baseline else 0.5,
                        "unsupported_rate": 0.0 if baseline else 0.5,
                        "safety_failure": 0.0 if baseline else 0.5,
                    },
                    checks=(),
                )
            await evaluations.finalize(
                "owner",
                item.id,
                status="completed",
                passed=True,
                aggregate_metrics={"case_count": 1},
            )
            ids.append(item.id)
        drift = await DriftService(store.session_factory, evaluations).compare(
            "owner",
            project_id="project",
            baseline_eval_id=ids[0],
            candidate_eval_id=ids[1],
            thresholds=DriftThresholds(minimum_sample_size=2),
        )
        approvals = ApprovalRepository(store.session_factory)
        candidates = OptimizationCandidateService(store.session_factory, approvals)
        candidate = await candidates.create(
            "owner",
            project_id="project",
            candidate_type="config",
            change_summary="Adopt evaluated revision.",
            proposal_metadata={"component": "retriever", "revision_hash": "c" * 64},
            rollback_plan="Restore baseline revision.",
            target_revision="config-candidate",
            baseline_eval_id=ids[0],
            candidate_eval_id=ids[1],
            drift_report_id=drift.id,
        )
        blocked_without_receipt = False
        try:
            await candidates.promote(
                "owner", candidate.id, project_id="project", expected_version=1
            )
        except CandidateConflictError:
            blocked_without_receipt = True
        approval_id, tool_call_id = await candidates.request_approval(
            "owner", candidate.id, project_id="project", expected_version=1
        )
        decided = await approvals.decide_exact_for_owner(
            user_id="owner",
            run_id=candidate.id,
            tool_call_id=tool_call_id,
            status=ApprovalStatus.APPROVED,
            reason="human_approved",
        )
        approved = await candidates.approve(
            "owner", candidate.id, project_id="project", expected_version=1, approval_id=approval_id
        )
        promoted = await candidates.promote(
            "owner", candidate.id, project_id="project", expected_version=2
        )
        replay_blocked = False
        try:
            await candidates.approve(
                "owner",
                candidate.id,
                project_id="project",
                expected_version=1,
                approval_id=approval_id,
            )
        except CandidateConflictError:
            replay_blocked = True
        await store.close()
    observation = {
        "baseline_revision": "config-baseline",
        "candidate_revision": "config-candidate",
        "drift_report_bound": candidate.drift_report_id == drift.id,
        "drift_warning_metrics": sorted(str(item["metric"]) for item in drift.warnings),
        "drift_pass_rate_delta": drift.deltas["pass_rate"],
        "blocked_without_receipt": blocked_without_receipt,
        "approval_decided": decided,
        "states": [candidate.state.value, approved.state.value, promoted.state.value],
        "receipt_replay_blocked": replay_blocked,
    }
    invariants = {
        "drift_is_computed_and_persisted": candidate.drift_report_id == drift.id
        and drift.deltas["pass_rate"] == -1.0
        and {str(item["metric"]) for item in drift.warnings}
        >= {"pass_rate", "mean_score", "unsupported_claim_rate"},
        "drift_candidate_starts_proposed": candidate.state.value == "proposed" and ids[0] != ids[1],
        "promotion_requires_approval": blocked_without_receipt,
        "exact_receipt_advances_once": decided
        and approved.state.value == "approved"
        and replay_blocked,
        "promotion_records_declared_revision_only": promoted.state.value == "promoted"
        and promoted.target_revision == "config-candidate",
    }
    return _outcome(started, invariants, observation)


_SCENARIOS = (
    ("unsafe_write_approval", _scenario_unsafe_write),
    ("provider_resilience", _scenario_provider_resilience),
    ("grounded_document_workflow", _scenario_grounding),
    ("reflection_disabled_vs_enabled", _scenario_reflection),
    ("duplicate_side_effect_replay", _scenario_duplicate_effect),
    ("budget_reservation_provider_failure", _scenario_budget_failure),
    ("context_provenance_key_rotation_interruption", _scenario_context_rotation),
    ("share_grant_revoke_expiry_redaction", _scenario_share_grants),
    ("signed_child_envelope_replay", _scenario_child_envelope),
    ("durable_job_restart_lease_loss", _scenario_durable_job),
    ("sandbox_breakout_probes", _scenario_sandbox_breakout),
    ("drift_candidate_exact_approval", _scenario_drift_approval),
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
        scenario_passed_iterations = iterations - len(failures) if observations_stable else 0
        failed_iterations += iterations - scenario_passed_iterations
        scenario_tokens = sum(int(item["tokens"]) for item in outcomes)
        total_tokens += scenario_tokens
        reports.append(
            {
                "id": name,
                "iterations": iterations,
                "passed_iterations": scenario_passed_iterations,
                "pass_rate": round(scenario_passed_iterations / iterations, 4),
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
    workspace_clean_before = not git_before
    workspace_clean_after = not git_after
    workspace_unchanged = git_before == git_after
    workspace_valid = workspace_clean_before and workspace_clean_after and workspace_unchanged
    if not workspace_valid:
        all_failures.append(
            {
                "scenario": "workspace",
                "iteration": 0,
                "failed_invariants": [
                    name
                    for name, ok in {
                        "workspace_clean_before": workspace_clean_before,
                        "workspace_clean_after": workspace_clean_after,
                        "workspace_unchanged": workspace_unchanged,
                    }.items()
                    if not ok
                ],
            }
        )
    passed_iterations = (
        0 if not workspace_valid else iterations * len(_SCENARIOS) - failed_iterations
    )
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
            "workspace_unchanged": workspace_unchanged,
            "clean_before": workspace_clean_before,
            "clean_after": workspace_clean_after,
        },
        "summary": {
            "passed": not all_failures and workspace_valid,
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
