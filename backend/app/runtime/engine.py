"""Budgeted, provider-neutral, event-driven agent loop."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import re
import time
from collections.abc import Callable, Coroutine, Sequence
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeVar

from app.runtime.events import AgentEvent, AgentEventKind, EventSink, NullEventSink
from app.runtime.models import Message, Role, TokenUsage, ToolCall
from app.runtime.ports import ModelProvider, PolicyAwareToolExecutor, ToolAuthorizer, ToolExecutor
from app.security.approvals import AuthorizationOutcome, AuthorizationRequest
from app.security.policy import (
    PolicyAction,
    PolicyDecision,
    PolicyEngine,
    PolicyRequest,
    canonical_arguments_hash,
    canonical_arguments_snapshot,
    canonical_tool_name,
)

T = TypeVar("T")
Clock = Callable[[], float]

# Approval hook: (tool_name, tool_call_id, arguments) -> approved?
ApprovalHook = Callable[[str, str, dict[str, Any]], Coroutine[Any, Any, bool]]


class StopReason(StrEnum):
    COMPLETED = "completed"
    ITERATION_BUDGET_EXHAUSTED = "iteration_budget_exhausted"
    TOOL_BUDGET_EXHAUSTED = "tool_budget_exhausted"
    TOKEN_BUDGET_EXHAUSTED = "token_budget_exhausted"
    TIME_BUDGET_EXHAUSTED = "time_budget_exhausted"
    POLICY_DENIED = "policy_denied"
    APPROVAL_TIMEOUT = "approval_timeout"
    APPROVAL_UNAVAILABLE = "approval_unavailable"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class RuntimeBudget:
    max_iterations: int = 8
    max_tool_calls: int = 8
    max_tokens: int = 64_000
    max_seconds: float = 90.0
    max_tool_result_chars: int = 12_000
    final_synthesis_tokens: int = 2_048

    def __post_init__(self) -> None:
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be at least one")
        if self.max_tool_calls < 0 or self.max_tokens < 0 or self.max_seconds <= 0:
            raise ValueError("tool/token/time budgets cannot be negative or zero")


@dataclass(frozen=True, slots=True)
class AgentResult:
    content: str
    stop_reason: StopReason
    iterations: int
    tool_calls: tuple[dict[str, Any], ...]
    usage: TokenUsage
    error: str | None = None


@dataclass(frozen=True, slots=True)
class _NativeToolBinding:
    """Scalar native identity captured before any runtime collaborator is invoked."""

    tool_call_id: str
    tool_name: str
    arguments_hash: str
    arguments_json: str


@dataclass(frozen=True, slots=True)
class _PolicyExecutionBinding:
    tool_call_id: str
    tool_name: str
    arguments_hash: str
    arguments_json: str
    request: PolicyRequest
    action: PolicyAction


@dataclass(frozen=True, slots=True)
class _ProviderToolCallCopies:
    """Independent native identity, provider-history, and execution snapshots."""

    binding: _NativeToolBinding
    history_call: ToolCall
    execution_call: ToolCall


class _ProviderToolCallSnapshotError(Exception):
    """A provider call could not be safely detached before yielding control."""

    def __init__(self, tool_call_id: str, tool_name: str) -> None:
        super().__init__("provider tool call snapshot unavailable")
        self.tool_call_id = tool_call_id
        self.tool_name = tool_name


class AgentRuntime:
    def __init__(
        self,
        model: ModelProvider,
        tools: ToolExecutor,
        *,
        events: EventSink | None = None,
        budget: RuntimeBudget | None = None,
        clock: Clock = time.monotonic,
        approval_hook: ApprovalHook | None = None,
        policy_engine: PolicyEngine | None = None,
        authorizer: ToolAuthorizer | None = None,
        approval_timeout_seconds: float = 30.0,
    ) -> None:
        if approval_timeout_seconds <= 0:
            raise ValueError("approval_timeout_seconds must be positive")
        self._model = model
        self._tools = tools
        self._events = events or NullEventSink()
        self._budget = budget or RuntimeBudget()
        self._clock = clock
        self._approval_hook = approval_hook
        self._policy_engine = policy_engine
        self._authorizer = authorizer
        self._approval_timeout_seconds = approval_timeout_seconds

    async def run(self, messages: Sequence[Message]) -> AgentResult:
        history = list(self._snapshot_history(messages))
        started_at = self._clock()
        iterations = 0
        calls: list[dict[str, Any]] = []
        seen_calls: set[str] = set()
        usage = TokenUsage()
        content = ""
        await self._emit(AgentEventKind.RUN_STARTED, 0)
        try:
            while iterations < self._budget.max_iterations:
                if self._expired(started_at):
                    return await self._stop(
                        StopReason.TIME_BUDGET_EXHAUSTED, content, iterations, calls, usage
                    )
                iterations += 1
                await self._emit(AgentEventKind.ITERATION_STARTED, iterations)
                remaining_tokens = max(1, self._budget.max_tokens - usage.total_tokens)
                remaining_seconds = self._budget.max_seconds - (self._clock() - started_at)
                if remaining_seconds <= 0:
                    raise TimeoutError
                response = await asyncio.wait_for(
                    self._model.complete(
                        self._snapshot_history(history),
                        self._tools.definitions(),
                        max_tokens=min(4096, remaining_tokens),
                    ),
                    timeout=remaining_seconds,
                )
                # This must be the first work after the provider returns: no clock, event sink,
                # history append, or other collaborator may observe provider-owned calls before
                # scalar bindings and independent history/execution copies have been captured.
                snapshot_error: _ProviderToolCallSnapshotError | None = None
                try:
                    call_copies = self._snapshot_provider_tool_calls(
                        response.tool_calls, policy_mode=self._policy_engine is not None
                    )
                except _ProviderToolCallSnapshotError as error:
                    snapshot_error = error
                    call_copies = ()
                tool_calls = tuple(item.execution_call for item in call_copies)
                history_tool_calls = tuple(item.history_call for item in call_copies)
                native_bindings = tuple(item.binding for item in call_copies)
                if self._expired(started_at):
                    raise TimeoutError

                # Capture scalar response fields before an event sink can mutate the provider
                # response. Cumulative usage is distinct from the per-response event value.
                response_content = response.content if isinstance(response.content, str) else None
                raw_stop_reason = response.provider_stop_reason
                provider_stop_reason = raw_stop_reason if isinstance(raw_stop_reason, str) else None
                response_usage = TokenUsage(
                    response.usage.input_tokens, response.usage.output_tokens
                )
                has_tool_calls = bool(tool_calls) or snapshot_error is not None
                usage += response_usage
                if response_content:
                    content = response_content
                await self._emit(
                    AgentEventKind.MODEL_RESPONSE,
                    iterations,
                    {"provider_stop_reason": provider_stop_reason},
                    response_usage,
                )
                if response_content:
                    # Text accompanying tool calls is progress, not the final answer.
                    event_kind = (
                        AgentEventKind.MODEL_PROGRESS
                        if has_tool_calls
                        else AgentEventKind.TEXT_DELTA
                    )
                    await self._emit(event_kind, iterations, {"text": response_content})
                if snapshot_error is not None:
                    failed_call = ToolCall(snapshot_error.tool_call_id, snapshot_error.tool_name)
                    await self._emit(
                        AgentEventKind.TOOL_CALL_REQUESTED,
                        iterations,
                        {"id": failed_call.id, "name": failed_call.name},
                    )
                    await self._emit_policy_failure(
                        failed_call, iterations, "policy_metadata_unavailable"
                    )
                    await self._record_denial(
                        failed_call, iterations, calls, "policy_metadata_unavailable"
                    )
                    return await self._stop(
                        StopReason.POLICY_DENIED, content, iterations, calls, usage
                    )
                if usage.total_tokens > self._budget.max_tokens:
                    return await self._finalize(
                        StopReason.TOKEN_BUDGET_EXHAUSTED,
                        history,
                        content,
                        iterations,
                        calls,
                        usage,
                        started_at,
                    )
                if not tool_calls:
                    return await self._stop(StopReason.COMPLETED, content, iterations, calls, usage)

                history.append(
                    Message(Role.ASSISTANT, response_content or "", tool_calls=history_tool_calls)
                )
                for call_index, call in enumerate(tool_calls):
                    if len(calls) >= self._budget.max_tool_calls:
                        return await self._finalize(
                            StopReason.TOOL_BUDGET_EXHAUSTED,
                            history,
                            content,
                            iterations,
                            calls,
                            usage,
                            started_at,
                        )
                    call_key = json.dumps(
                        [call.name, dict(call.arguments)],
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    )
                    if call_key in seen_calls:
                        duplicate = {"error": "Duplicate tool call blocked; use existing result."}
                        history.append(
                            Message(
                                Role.TOOL,
                                json.dumps(duplicate, separators=(",", ":")),
                                tool_call_id=call.id,
                            )
                        )
                        continue
                    seen_calls.add(call_key)
                    request_data: dict[str, Any] = {"id": call.id, "name": call.name}
                    native_binding = native_bindings[call_index]
                    if self._policy_engine is None:
                        request_data["arguments"] = copy.deepcopy(dict(call.arguments))
                    else:
                        assert native_binding is not None
                        request_data = {
                            "id": native_binding.tool_call_id,
                            "name": native_binding.tool_name,
                            "arguments_hash": native_binding.arguments_hash,
                        }
                    await self._emit(
                        AgentEventKind.TOOL_CALL_REQUESTED,
                        iterations,
                        request_data,
                    )
                    policy_binding: _PolicyExecutionBinding | None = None
                    if self._policy_engine is not None:
                        assert native_binding is not None
                        enforcement = await self._enforce_policy(
                            call, native_binding, iterations, calls, started_at
                        )
                        if isinstance(enforcement, StopReason):
                            return await self._stop(enforcement, content, iterations, calls, usage)
                        policy_binding = enforcement
                    # Deprecated compatibility path. It is deliberately unreachable in policy
                    # mode, so a legacy hook cannot bypass or replace policy authorization.
                    elif (
                        self._approval_hook
                        and hasattr(self._tools, "tool_requires_approval")
                        and self._tools.tool_requires_approval(call.name)
                    ):
                        await self._emit(
                            AgentEventKind.APPROVAL_REQUIRED,
                            iterations,
                            {"id": call.id, "name": call.name, "arguments": dict(call.arguments)},
                        )
                        approved = await self._approval_hook(
                            call.name, call.id, dict(call.arguments)
                        )
                        if not approved:
                            denied_output = {"error": "User denied this tool call"}
                            record = {
                                "tool": call.name,
                                "parameters": dict(call.arguments),
                                "result": denied_output,
                                "status": "denied",
                            }
                            calls.append(record)
                            await self._emit(
                                AgentEventKind.TOOL_DENIED,
                                iterations,
                                {
                                    "id": call.id,
                                    "name": call.name,
                                    "arguments": dict(call.arguments),
                                },
                            )
                            history.append(
                                Message(
                                    Role.TOOL,
                                    json.dumps(denied_output, separators=(",", ":")),
                                    tool_call_id=call.id,
                                )
                            )
                            continue
                    if policy_binding is not None:
                        try:
                            call = self._prepare_policy_execution_call(call, policy_binding)
                        except Exception:
                            bound_call = ToolCall(
                                policy_binding.tool_call_id, policy_binding.tool_name
                            )
                            reason_code = "binding_mismatch"
                            if policy_binding.action is PolicyAction.ASK:
                                await self._emit_approval_failure(
                                    bound_call,
                                    iterations,
                                    policy_binding.arguments_hash,
                                    reason_code,
                                )
                                stop_reason = StopReason.APPROVAL_UNAVAILABLE
                            else:
                                await self._emit_policy_failure(
                                    bound_call,
                                    iterations,
                                    reason_code,
                                    policy_binding.arguments_hash,
                                )
                                stop_reason = StopReason.POLICY_DENIED
                            await self._record_denial(
                                bound_call,
                                iterations,
                                calls,
                                reason_code,
                                policy_binding.arguments_hash,
                            )
                            return await self._stop(stop_reason, content, iterations, calls, usage)
                    try:
                        output = await self._within_deadline(self._tools.execute(call), started_at)
                    except Exception as tool_err:
                        # Reflexion: feed error back to the LLM so it can self-correct
                        error_output = {
                            "error": f"{type(tool_err).__name__}: {tool_err}",
                            "reflexion_hint": "The tool call failed. Analyze the error, "
                            "adjust your approach, and try again with corrected parameters "
                            "or a different tool.",
                        }
                        record = {
                            "tool": call.name,
                            "parameters": dict(call.arguments),
                            "result": error_output,
                            "status": "error",
                        }
                        calls.append(record)
                        if policy_binding is None:
                            completed_data = {
                                "id": call.id,
                                "name": call.name,
                                "arguments": dict(call.arguments),
                                "output": error_output,
                            }
                        else:
                            error_serialized = json.dumps(
                                error_output, sort_keys=True, separators=(",", ":")
                            )
                            completed_data = self._policy_tool_result_data(
                                call,
                                policy_binding.arguments_hash,
                                error_serialized,
                                "error",
                            )
                        await self._emit(
                            AgentEventKind.TOOL_CALL_COMPLETED,
                            iterations,
                            completed_data,
                        )
                        history.append(
                            Message(
                                Role.TOOL,
                                json.dumps(error_output, separators=(",", ":")),
                                tool_call_id=call.id,
                            )
                        )
                        continue
                    record = {
                        "tool": call.name,
                        "parameters": dict(call.arguments),
                        "result": dict(output),
                        "status": "success",
                    }
                    calls.append(record)
                    serialized = json.dumps(
                        output, sort_keys=True, separators=(",", ":"), default=str
                    )
                    if policy_binding is None:
                        completed_data = {
                            "id": call.id,
                            "name": call.name,
                            "arguments": dict(call.arguments),
                            "output": dict(output),
                        }
                    else:
                        completed_data = self._policy_tool_result_data(
                            call,
                            policy_binding.arguments_hash,
                            serialized,
                            "success",
                        )
                    await self._emit(
                        AgentEventKind.TOOL_CALL_COMPLETED,
                        iterations,
                        completed_data,
                    )
                    # Emit TOOL_PROGRESS chunks for large results
                    if len(serialized) > 500:
                        chunk_size = 500
                        for i in range(0, len(serialized), chunk_size):
                            if policy_binding is None:
                                progress_data = {
                                    "id": call.id,
                                    "name": call.name,
                                    "chunk": serialized[i : i + chunk_size],
                                    "offset": i,
                                    "total": len(serialized),
                                }
                            else:
                                progress_data = dict(completed_data)
                                progress_data.update({"offset": i, "total": len(serialized)})
                            await self._emit(
                                AgentEventKind.TOOL_PROGRESS,
                                iterations,
                                progress_data,
                            )
                    if len(serialized) > self._budget.max_tool_result_chars:
                        serialized = (
                            serialized[: self._budget.max_tool_result_chars] + "...[truncated]"
                        )
                    history.append(Message(Role.TOOL, serialized, tool_call_id=call.id))
            return await self._finalize(
                StopReason.ITERATION_BUDGET_EXHAUSTED,
                history,
                content,
                iterations,
                calls,
                usage,
                started_at,
            )
        except TimeoutError:
            return await self._stop(
                StopReason.TIME_BUDGET_EXHAUSTED, content, iterations, calls, usage
            )
        except Exception as error:
            return await self._stop(
                StopReason.ERROR,
                content,
                iterations,
                calls,
                usage,
                f"{type(error).__name__}: {error}",
            )

    @staticmethod
    def _snapshot_history(messages: Sequence[Message]) -> tuple[Message, ...]:
        """Build a detached provider view that cannot mutate or observe runtime history."""
        snapshots: list[Message] = []
        for message in messages:
            tool_calls = tuple(
                ToolCall(call.id, call.name, copy.deepcopy(dict(call.arguments)))
                for call in message.tool_calls
            )
            snapshots.append(
                Message(
                    message.role,
                    message.content,
                    tool_call_id=message.tool_call_id,
                    tool_calls=tool_calls,
                    images=tuple(message.images),
                )
            )
        return tuple(snapshots)

    @staticmethod
    def _snapshot_provider_tool_calls(
        provider_calls: Sequence[ToolCall], *, policy_mode: bool
    ) -> tuple[_ProviderToolCallCopies, ...]:
        """Bind identity and make unrelated history/execution copies before yielding control."""
        snapshots: list[_ProviderToolCallCopies] = []
        for provider_call in provider_calls:
            try:
                raw_id = provider_call.id
            except Exception:
                raw_id = None
            try:
                raw_name = provider_call.name
            except Exception:
                raw_name = None
            safe_id = raw_id if isinstance(raw_id, str) and raw_id else "unavailable"
            safe_name = raw_name if isinstance(raw_name, str) and raw_name else "unavailable"
            try:
                if raw_id != safe_id or raw_name != safe_name:
                    raise ValueError("provider tool identity is invalid")
                if policy_mode:
                    canonical_name = canonical_tool_name(safe_name)
                    if safe_name != canonical_name:
                        raise ValueError("provider tool name is not canonical")
                    arguments = canonical_arguments_snapshot(provider_call.arguments)
                    arguments_json = json.dumps(
                        arguments,
                        ensure_ascii=False,
                        allow_nan=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    binding = _NativeToolBinding(
                        safe_id,
                        canonical_name,
                        canonical_arguments_hash(arguments),
                        arguments_json,
                    )
                else:
                    canonical_name = safe_name
                    arguments = copy.deepcopy(dict(provider_call.arguments))
                    arguments_json = json.dumps(
                        arguments,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    )
                    binding = _NativeToolBinding(
                        safe_id,
                        canonical_name,
                        hashlib.sha256(arguments_json.encode("utf-8")).hexdigest(),
                        arguments_json,
                    )
                snapshots.append(
                    _ProviderToolCallCopies(
                        binding,
                        ToolCall(safe_id, canonical_name, copy.deepcopy(arguments)),
                        ToolCall(safe_id, canonical_name, copy.deepcopy(arguments)),
                    )
                )
            except Exception:
                raise _ProviderToolCallSnapshotError(safe_id, safe_name) from None
        return tuple(snapshots)

    async def _enforce_policy(
        self,
        call: ToolCall,
        native_binding: _NativeToolBinding,
        iteration: int,
        calls: list[dict[str, Any]],
        started_at: float,
    ) -> StopReason | _PolicyExecutionBinding:
        """Evaluate policy against the scalar identity bound at provider return."""
        arguments_hash = native_binding.arguments_hash
        tool_name = native_binding.tool_name
        event_call = ToolCall(native_binding.tool_call_id, native_binding.tool_name)
        try:
            binding_matches = (
                call.id == native_binding.tool_call_id
                and call.name == native_binding.tool_name
                and canonical_tool_name(call.name) == native_binding.tool_name
                and canonical_arguments_hash(call.arguments) == native_binding.arguments_hash
            )
        except Exception:
            binding_matches = False
        if not binding_matches:
            await self._emit_policy_failure(
                event_call, iteration, "binding_mismatch", arguments_hash
            )
            await self._record_denial(
                event_call, iteration, calls, "binding_mismatch", arguments_hash
            )
            return StopReason.POLICY_DENIED
        if not isinstance(self._tools, PolicyAwareToolExecutor):
            await self._emit_policy_failure(
                event_call, iteration, "policy_metadata_unavailable", arguments_hash
            )
            await self._record_denial(
                event_call,
                iteration,
                calls,
                "policy_metadata_unavailable",
                arguments_hash,
            )
            return StopReason.POLICY_DENIED

        request: PolicyRequest | None
        try:
            request = self._tools.policy_request(call)
        except Exception:
            request = None

        try:
            binding_matches = (
                call.id == native_binding.tool_call_id
                and call.name == native_binding.tool_name
                and canonical_tool_name(call.name) == native_binding.tool_name
                and canonical_arguments_hash(call.arguments) == native_binding.arguments_hash
            )
        except Exception:
            binding_matches = False
        if not binding_matches:
            await self._emit_policy_failure(
                event_call, iteration, "binding_mismatch", arguments_hash
            )
            await self._record_denial(
                event_call, iteration, calls, "binding_mismatch", arguments_hash
            )
            return StopReason.POLICY_DENIED

        try:
            request_matches = request is not None and request.tool_name == tool_name
        except Exception:
            request_matches = False
        if not request_matches:
            await self._emit_policy_failure(
                event_call, iteration, "policy_metadata_unavailable", arguments_hash
            )
            await self._record_denial(
                event_call,
                iteration,
                calls,
                "policy_metadata_unavailable",
                arguments_hash,
            )
            return StopReason.POLICY_DENIED
        assert request is not None

        try:
            assert self._policy_engine is not None
            decision = self._policy_engine.evaluate(request)
            if not isinstance(decision, PolicyDecision):
                raise TypeError("policy engine returned an invalid decision")
            if decision.risk_classes != request.risk_classes:
                raise ValueError("policy decision risk binding mismatch")
        except Exception:
            await self._emit_policy_failure(
                event_call, iteration, "policy_engine_unavailable", arguments_hash
            )
            await self._record_denial(
                event_call, iteration, calls, "policy_engine_unavailable", arguments_hash
            )
            return StopReason.POLICY_DENIED

        decision_reason_codes = {
            PolicyAction.ALLOW: "policy_allowed",
            PolicyAction.ASK: "approval_required",
            PolicyAction.DENY: "policy_denied",
        }
        policy_data: dict[str, Any] = {
            "id": native_binding.tool_call_id,
            "name": tool_name,
            "action": decision.action.value,
            "reason_code": decision_reason_codes[decision.action],
            "risk_classes": sorted(risk.value for risk in decision.risk_classes),
            "arguments_hash": arguments_hash,
        }
        if decision.matched_rule_id and re.fullmatch(
            r"[A-Za-z0-9_.:-]{1,128}", decision.matched_rule_id
        ):
            policy_data["matched_rule_id"] = decision.matched_rule_id
        await self._emit(AgentEventKind.POLICY_DECIDED, iteration, policy_data)

        binding = _PolicyExecutionBinding(
            native_binding.tool_call_id,
            tool_name,
            arguments_hash,
            native_binding.arguments_json,
            request,
            decision.action,
        )
        if decision.action is PolicyAction.ALLOW:
            return binding
        if decision.action is PolicyAction.DENY:
            await self._record_denial(event_call, iteration, calls, "policy_denied", arguments_hash)
            return StopReason.POLICY_DENIED

        if self._authorizer is None:
            await self._record_denial(
                event_call, iteration, calls, "approval_unavailable", arguments_hash
            )
            return StopReason.APPROVAL_UNAVAILABLE

        authorization_request = AuthorizationRequest(
            tool_call_id=native_binding.tool_call_id,
            tool_name=tool_name,
            arguments_hash=arguments_hash,
            risk_classes=decision.risk_classes,
            matched_rule_id=decision.matched_rule_id,
        )
        approval_data = {
            "id": native_binding.tool_call_id,
            "name": tool_name,
            "arguments_hash": arguments_hash,
            "risk_classes": sorted(risk.value for risk in decision.risk_classes),
        }
        await self._emit(AgentEventKind.APPROVAL_REQUIRED, iteration, approval_data)

        runtime_remaining = self._budget.max_seconds - (self._clock() - started_at)
        timeout = min(runtime_remaining, self._approval_timeout_seconds)
        if timeout <= 0:
            await self._emit_approval_failure(
                event_call, iteration, arguments_hash, "approval_timeout"
            )
            await self._record_denial(
                event_call, iteration, calls, "approval_timeout", arguments_hash
            )
            return StopReason.APPROVAL_TIMEOUT
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        authorization_task = asyncio.create_task(self._authorizer.authorize(authorization_request))
        try:
            done, _ = await asyncio.wait(
                {authorization_task},
                timeout=max(0.0, deadline - loop.time()),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if authorization_task not in done or loop.time() >= deadline:
                authorization_task.cancel()
                authorization_task.add_done_callback(self._consume_background_task)
                await self._emit_approval_failure(
                    event_call, iteration, arguments_hash, "approval_timeout"
                )
                await self._record_denial(
                    event_call, iteration, calls, "approval_timeout", arguments_hash
                )
                return StopReason.APPROVAL_TIMEOUT
            outcome = authorization_task.result()
        except asyncio.CancelledError:
            if not authorization_task.done():
                authorization_task.cancel()
                authorization_task.add_done_callback(self._consume_background_task)
            raise
        except Exception:
            await self._emit_approval_failure(
                event_call, iteration, arguments_hash, "approval_unavailable"
            )
            await self._record_denial(
                event_call, iteration, calls, "approval_unavailable", arguments_hash
            )
            return StopReason.APPROVAL_UNAVAILABLE

        if not isinstance(outcome, AuthorizationOutcome) or not outcome.binds(
            authorization_request
        ):
            await self._emit_approval_failure(
                event_call, iteration, arguments_hash, "approval_binding_mismatch"
            )
            await self._record_denial(
                event_call,
                iteration,
                calls,
                "approval_binding_mismatch",
                arguments_hash,
            )
            return StopReason.APPROVAL_UNAVAILABLE

        await self._emit(
            AgentEventKind.APPROVAL_DECIDED,
            iteration,
            {
                "id": native_binding.tool_call_id,
                "name": tool_name,
                "arguments_hash": arguments_hash,
                "approved": outcome.approved,
                "reason_code": outcome.reason_code,
            },
        )
        if outcome.approved:
            return binding
        await self._record_denial(event_call, iteration, calls, outcome.reason_code, arguments_hash)
        return StopReason.POLICY_DENIED

    def _prepare_policy_execution_call(
        self, call: ToolCall, binding: _PolicyExecutionBinding
    ) -> ToolCall:
        """Revalidate exact identity, arguments, and policy metadata before dispatch."""
        if not isinstance(self._tools, PolicyAwareToolExecutor):
            raise TypeError("policy-aware tool metadata is unavailable")

        execution_arguments = canonical_arguments_snapshot(call.arguments)
        arguments_hash = canonical_arguments_hash(execution_arguments)
        if (
            call.id != binding.tool_call_id
            or call.name != binding.tool_name
            or call.name != canonical_tool_name(call.name)
            or arguments_hash != binding.arguments_hash
        ):
            raise ValueError("policy execution binding changed")

        bound_arguments = canonical_arguments_snapshot(json.loads(binding.arguments_json))
        if canonical_arguments_hash(bound_arguments) != binding.arguments_hash:
            raise ValueError("policy execution binding changed")
        verification_call = ToolCall(
            binding.tool_call_id,
            binding.tool_name,
            canonical_arguments_snapshot(bound_arguments),
        )
        request = self._tools.policy_request(verification_call)
        verification_hash = canonical_arguments_hash(verification_call.arguments)
        if (
            verification_call.id != binding.tool_call_id
            or verification_call.name != binding.tool_name
            or request.tool_name != binding.tool_name
            or request != binding.request
            or verification_hash != binding.arguments_hash
        ):
            raise ValueError("policy execution binding changed")

        # Dispatch only bound identity fields and detached, validated arguments. Neither the
        # ToolCall nor its argument graph has been exposed to a policy or authorization
        # collaborator.
        execution_call = ToolCall(
            binding.tool_call_id,
            binding.tool_name,
            canonical_arguments_snapshot(bound_arguments),
        )
        if canonical_arguments_hash(execution_call.arguments) != binding.arguments_hash:
            raise ValueError("policy execution arguments changed")
        return execution_call

    @staticmethod
    def _policy_tool_result_data(
        call: ToolCall, arguments_hash: str, serialized_output: str, status: str
    ) -> dict[str, Any]:
        encoded = serialized_output.encode("utf-8")
        return {
            "id": call.id,
            "name": call.name,
            "arguments_hash": arguments_hash,
            "output_hash": hashlib.sha256(encoded).hexdigest(),
            "output_size": len(encoded),
            "status": status,
        }

    @staticmethod
    def _consume_background_task(task: asyncio.Task[Any]) -> None:
        """Retrieve the terminal state of a timed-out task without delaying the runtime."""
        with suppress(BaseException):
            task.exception()

    async def _emit_policy_failure(
        self,
        call: ToolCall,
        iteration: int,
        reason_code: str,
        arguments_hash: str | None = None,
    ) -> None:
        data: dict[str, Any] = {
            "id": call.id,
            "name": call.name,
            "action": PolicyAction.DENY.value,
            "reason_code": reason_code,
        }
        if arguments_hash is not None:
            data["arguments_hash"] = arguments_hash
        await self._emit(AgentEventKind.POLICY_DECIDED, iteration, data)

    async def _emit_approval_failure(
        self, call: ToolCall, iteration: int, arguments_hash: str, reason_code: str
    ) -> None:
        await self._emit(
            AgentEventKind.APPROVAL_DECIDED,
            iteration,
            {
                "id": call.id,
                "name": call.name,
                "arguments_hash": arguments_hash,
                "approved": False,
                "reason_code": reason_code,
            },
        )

    async def _record_denial(
        self,
        call: ToolCall,
        iteration: int,
        calls: list[dict[str, Any]],
        reason_code: str,
        arguments_hash: str | None = None,
    ) -> None:
        result = {"error": "Tool call denied", "reason_code": reason_code}
        calls.append(
            {
                "tool": call.name,
                "parameters": {},
                "result": result,
                "status": "denied",
            }
        )
        data: dict[str, Any] = {
            "id": call.id,
            "name": call.name,
            "reason_code": reason_code,
        }
        if arguments_hash is not None:
            data["arguments_hash"] = arguments_hash
        await self._emit(AgentEventKind.TOOL_DENIED, iteration, data)

    async def _finalize(
        self,
        reason: StopReason,
        history: list[Message],
        content: str,
        iterations: int,
        calls: list[dict[str, Any]],
        usage: TokenUsage,
        started_at: float,
    ) -> AgentResult:
        """Make one bounded, tool-free synthesis attempt before a budget stop."""
        if self._expired(started_at):
            return await self._stop(reason, content, iterations, calls, usage)
        history.append(
            Message(
                Role.USER,
                "Execution budget reached. Do not call tools. Produce the best complete final "
                "answer now from the evidence already available. State any missing coverage.",
            )
        )
        try:
            response = await self._within_deadline(
                self._model.complete(
                    self._snapshot_history(history),
                    (),
                    max_tokens=self._budget.final_synthesis_tokens,
                ),
                started_at,
            )
            usage += response.usage
            if response.content:
                content = response.content
                await self._emit(AgentEventKind.TEXT_DELTA, iterations, {"text": content})
        except (TimeoutError, Exception):
            # Preserve the best content already produced; stop reason remains explicit.
            pass
        return await self._stop(reason, content, iterations, calls, usage)

    def _expired(self, started_at: float) -> bool:
        return self._clock() - started_at >= self._budget.max_seconds

    async def _within_deadline(self, awaitable: Coroutine[Any, Any, T], started_at: float) -> T:
        remaining = self._budget.max_seconds - (self._clock() - started_at)
        if remaining <= 0:
            awaitable.close()
            raise TimeoutError
        result = await asyncio.wait_for(awaitable, timeout=remaining)
        if self._expired(started_at):
            raise TimeoutError
        return result

    async def _emit(
        self,
        kind: AgentEventKind,
        iteration: int,
        data: dict[str, Any] | None = None,
        usage: TokenUsage | None = None,
    ) -> None:
        await self._events.emit(AgentEvent(kind, iteration, data or {}, usage or TokenUsage()))

    async def _stop(
        self,
        reason: StopReason,
        content: str,
        iterations: int,
        calls: list[dict[str, Any]],
        usage: TokenUsage,
        error: str | None = None,
    ) -> AgentResult:
        await self._emit(
            AgentEventKind.RUN_STOPPED,
            iterations,
            {"reason": reason.value, "error": error},
            usage,
        )
        return AgentResult(content, reason, iterations, tuple(calls), usage, error)
