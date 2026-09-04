"""Budgeted, provider-neutral, event-driven agent loop."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import re
import time
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, TypeVar

import structlog

from app.runtime.capabilities import (
    ProviderCapabilities,
    UnsupportedProviderCapability,
    get_provider_capabilities,
)
from app.runtime.deadline import DeadlineExceededError, await_before_deadline, consume_detached_task
from app.runtime.events import AgentEvent, AgentEventKind, EventSink, NullEventSink
from app.runtime.models import Message, Role, TokenUsage, ToolCall
from app.runtime.monetary_budget import (
    DuplicateModelCharge,
    DurableModelChargeStateError,
    IndeterminateModelCharge,
    ModelBudgetExhausted,
    estimate_request_input_tokens,
)
from app.runtime.ports import (
    ModelProvider,
    PolicyAwareToolExecutor,
    PreparatoryToolAuthorizer,
    ToolAuthorizer,
    ToolExecutor,
)
from app.runtime.structured_output import ResponseContract, StructuredOutputError
from app.security.approvals import AuthorizationOutcome, AuthorizationRequest
from app.security.compliance import MandatoryComplianceService, default_compliance
from app.security.policy import (
    PolicyAction,
    PolicyDecision,
    PolicyEngine,
    PolicyRequest,
    RiskClass,
    canonical_arguments_hash,
    canonical_arguments_snapshot,
    canonical_tool_name,
)

if TYPE_CHECKING:
    from app.reflection.models import ReflectionPolicy

T = TypeVar("T")
Clock = Callable[[], float]
ResultRecorder = Callable[[str], Awaitable[None]]
logger = structlog.get_logger()
_RUNTIME_TERMINAL_CLEANUP_SECONDS = 0.025

# Approval hook: (tool_name, tool_call_id, arguments) -> approved?
ApprovalHook = Callable[[str, str, dict[str, Any]], Coroutine[Any, Any, bool]]


class StopReason(StrEnum):
    COMPLETED = "completed"
    ITERATION_BUDGET_EXHAUSTED = "iteration_budget_exhausted"
    TOOL_BUDGET_EXHAUSTED = "tool_budget_exhausted"
    TOKEN_BUDGET_EXHAUSTED = "token_budget_exhausted"
    CONTEXT_BUDGET_EXHAUSTED = "context_budget_exhausted"
    TIME_BUDGET_EXHAUSTED = "time_budget_exhausted"
    POLICY_DENIED = "policy_denied"
    APPROVAL_TIMEOUT = "approval_timeout"
    APPROVAL_UNAVAILABLE = "approval_unavailable"
    PROVIDER_CAPABILITY_UNSUPPORTED = "provider_capability_unsupported"
    STRUCTURED_OUTPUT_INVALID = "structured_output_invalid"
    PROVIDER_LENGTH_LIMIT = "provider_length_limit"
    PROVIDER_REFUSAL = "provider_refusal"
    PROVIDER_CONTENT_FILTER = "provider_content_filter"
    MONETARY_BUDGET_EXHAUSTED = "monetary_budget_exhausted"
    MODEL_CHARGE_DUPLICATE = "model_charge_duplicate"
    MODEL_CHARGE_INDETERMINATE = "model_charge_indeterminate"
    PROVIDER_ERROR = "provider_error"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class RuntimeBudget:
    max_iterations: int = 15
    max_tool_calls: int = 20
    max_tokens: int = 64_000
    max_seconds: float = 300.0
    max_tool_result_chars: int = 12_000
    final_synthesis_tokens: int = 2_048
    max_structured_retries: int = 1
    max_context_tokens: int = 200_000
    context_output_reserve_tokens: int = 4_096

    def __post_init__(self) -> None:
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be at least one")
        if self.max_tool_calls < 0 or self.max_tokens < 0 or self.max_seconds <= 0:
            raise ValueError("tool/token/time budgets cannot be negative or zero")
        if not 0 <= self.max_structured_retries <= 2:
            raise ValueError("max_structured_retries must be between zero and two")
        if (
            self.max_context_tokens < 1
            or not 0 <= self.context_output_reserve_tokens < self.max_context_tokens
        ):
            raise ValueError("context token budget and output reserve are invalid")


@dataclass(frozen=True, slots=True)
class AgentResult:
    content: str
    stop_reason: StopReason
    iterations: int
    tool_calls: tuple[dict[str, Any], ...]
    usage: TokenUsage
    error: str | None = None
    structured_output: object | None = None


@dataclass(slots=True)
class _RuntimeDeadlineState:
    deadline: float
    terminal_started: bool = False
    terminal_persisted: bool = False
    terminal_reason: StopReason | None = None
    terminal_error: str | None = None
    content: str = ""
    iterations: int = 0
    calls: tuple[dict[str, Any], ...] = ()
    usage: TokenUsage | None = None
    structured_output: object | None = None
    terminal_task: asyncio.Task[None] | None = None


_RUNTIME_DEADLINE_STATE: ContextVar[_RuntimeDeadlineState | None] = ContextVar(
    "runtime_deadline_state", default=None
)


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
    risk_classes: frozenset[RiskClass]
    matched_rule_id: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class _AuthorizationDecisionBinding:
    """Validated approval scalars detached from a collaborator-owned outcome."""

    approved: bool
    tool_call_id: str
    tool_name: str
    arguments_hash: str
    reason_code: str


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


_RuntimeDeadlineExceededError = DeadlineExceededError


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
        result_recorder: ResultRecorder | None = None,
        reflection_policy: ReflectionPolicy | None = None,
        reflection_hash_key: bytes | None = None,
        reflection_hash_scope: str = "",
        compliance: MandatoryComplianceService | None = default_compliance,
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
        self._result_recorder = result_recorder
        self._compliance = compliance
        from app.reflection.models import ReflectionPolicy as RuntimeReflectionPolicy
        from app.reflection.service import BoundedReflectionService

        self._reflection_policy = reflection_policy or RuntimeReflectionPolicy()
        self._reflection = BoundedReflectionService(
            model,
            self._reflection_policy,
            events=self._events,
            clock=clock,
            hash_key=reflection_hash_key,
            hash_scope=reflection_hash_scope,
        )

    async def run(
        self,
        messages: Sequence[Message],
        *,
        response_contract: ResponseContract | None = None,
        required_capabilities: ProviderCapabilities | None = None,
    ) -> AgentResult:
        started_at = self._clock()
        state = _RuntimeDeadlineState(deadline=started_at + self._budget.max_seconds)
        token = _RUNTIME_DEADLINE_STATE.set(state)
        try:
            return await await_before_deadline(
                self._run(
                    messages,
                    response_contract=response_contract,
                    required_capabilities=required_capabilities,
                    started_at=started_at,
                ),
                deadline=state.deadline,
                clock=self._clock,
            )
        except DeadlineExceededError:
            return await self._deadline_result(state)
        finally:
            _RUNTIME_DEADLINE_STATE.reset(token)

    async def _run(
        self,
        messages: Sequence[Message],
        *,
        response_contract: ResponseContract | None,
        required_capabilities: ProviderCapabilities | None,
        started_at: float,
    ) -> AgentResult:
        history = list(self._snapshot_history(messages))
        iterations = 0
        calls: list[dict[str, Any]] = []
        seen_calls: set[str] = set()
        usage = TokenUsage()
        content = ""
        structured_output: object | None = None
        structured_retries = 0
        tool_definitions = tuple(self._tools.definitions())
        requirements = self._provider_requirements(
            history,
            response_contract,
            required_capabilities,
            native_tools_required=bool(tool_definitions),
        )
        await self._emit(AgentEventKind.RUN_STARTED, 0)
        try:
            while iterations < self._budget.max_iterations:
                if self._expired(started_at):
                    return await self._stop(
                        StopReason.TIME_BUDGET_EXHAUSTED, content, iterations, calls, usage
                    )
                missing_capabilities = get_provider_capabilities(self._model).missing(requirements)
                if missing_capabilities:
                    return await self._reject_provider_capabilities(
                        missing_capabilities, content, iterations, calls, usage
                    )
                iterations += 1
                await self._emit(AgentEventKind.ITERATION_STARTED, iterations)
                context_allowance = (
                    self._budget.max_context_tokens - self._budget.context_output_reserve_tokens
                )
                if (
                    estimate_request_input_tokens(
                        history,
                        tool_definitions,
                        response_contract=response_contract,
                    )
                    > context_allowance
                ):
                    return await self._stop(
                        StopReason.CONTEXT_BUDGET_EXHAUSTED,
                        content,
                        iterations,
                        calls,
                        usage,
                    )
                remaining_tokens = max(1, self._budget.max_tokens - usage.total_tokens)
                provider_kwargs: dict[str, Any] = {"max_tokens": min(4096, remaining_tokens)}
                if response_contract is not None:
                    provider_kwargs["response_contract"] = response_contract
                if inspect.getattr_static(self._model, "routes_capabilities", False) is True:
                    provider_kwargs["required_capabilities"] = requirements
                try:
                    response = await self._within_deadline(
                        self._model.complete(
                            self._snapshot_history(history),
                            tool_definitions,
                            **provider_kwargs,
                        ),
                        started_at,
                    )
                except _RuntimeDeadlineExceededError:
                    raise
                except (
                    ModelBudgetExhausted,
                    DuplicateModelCharge,
                    IndeterminateModelCharge,
                    DurableModelChargeStateError,
                ) as error:
                    return await self._stop_for_budget_error(
                        error,
                        content=content,
                        iterations=iterations,
                        calls=calls,
                        usage=usage,
                    )
                except UnsupportedProviderCapability as error:
                    return await self._reject_provider_capabilities(
                        self._safe_missing_capability_names(error),
                        content,
                        iterations,
                        calls,
                        usage,
                    )
                except Exception as exc:
                    import structlog as _sl

                    _sl.get_logger().error("provider_call_exception", error=str(exc), exc_info=True)
                    return await self._stop(
                        StopReason.PROVIDER_ERROR,
                        content,
                        iterations,
                        calls,
                        usage,
                        "provider_call_failed",
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
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                    response.usage.cache_read_input_tokens,
                    response.usage.cache_write_input_tokens,
                )
                raw_actual_provider = getattr(response, "actual_provider", None)
                actual_provider = (
                    raw_actual_provider if isinstance(raw_actual_provider, str) else None
                )
                raw_actual_model = getattr(response, "actual_model", None)
                actual_model = raw_actual_model if isinstance(raw_actual_model, str) else None
                has_tool_calls = bool(tool_calls) or snapshot_error is not None
                usage += response_usage
                response_event_data = {}
                if provider_stop_reason is not None:
                    response_event_data["provider_stop_reason"] = provider_stop_reason
                if actual_provider is not None:
                    response_event_data["actual_provider"] = actual_provider
                if actual_model is not None:
                    response_event_data["actual_model"] = actual_model
                await self._emit(
                    AgentEventKind.MODEL_RESPONSE,
                    iterations,
                    response_event_data,
                    response_usage,
                )
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
                provider_reason = self._normalize_provider_stop_reason(
                    provider_stop_reason, bool(tool_calls)
                )
                if provider_reason not in (None, StopReason.COMPLETED):
                    return await self._stop(
                        provider_reason,
                        content,
                        iterations,
                        calls,
                        usage,
                        f"provider_stop_reason:{provider_reason.value}",
                    )
                if response_content and response_contract is None:
                    # Preserve the provider draft before optional reflection so a durable
                    # monetary failure can stop with the best already-produced answer.
                    content = response_content
                if response_content and (
                    not tool_calls and response_contract is None and self._reflection_policy.enabled
                ):
                    remaining_seconds = max(
                        0.0, self._budget.max_seconds - (self._clock() - started_at)
                    )
                    reflection = await self._reflection.reflect(
                        history,
                        response_content,
                        iteration=iterations,
                        timeout_seconds=remaining_seconds,
                        max_total_tokens=max(0, self._budget.max_tokens - usage.total_tokens),
                    )
                    response_content = reflection.content
                    usage += reflection.usage
                if response_content and self._compliance is not None:
                    response_content = self._compliance.enforce_output(response_content)
                if not tool_calls and response_contract is not None:
                    try:
                        structured_output = response_contract.parse_and_validate(
                            response_content or ""
                        )
                    except StructuredOutputError as error:
                        await self._emit(
                            AgentEventKind.STRUCTURED_OUTPUT_REJECTED,
                            iterations,
                            {
                                "code": error.code,
                                "retry": structured_retries < self._budget.max_structured_retries,
                            },
                        )
                        can_retry = (
                            structured_retries < self._budget.max_structured_retries
                            and iterations < self._budget.max_iterations
                            and usage.total_tokens < self._budget.max_tokens
                            and not self._expired(started_at)
                        )
                        if can_retry:
                            structured_retries += 1
                            history.append(
                                Message(
                                    Role.USER,
                                    "The previous response was invalid. Return exactly one "
                                    "JSON value matching schema "
                                    f"{response_contract.schema_id} version "
                                    f"{response_contract.schema_version}. Include no prose or "
                                    "markdown.",
                                )
                            )
                            continue
                        return await self._stop(
                            StopReason.STRUCTURED_OUTPUT_INVALID,
                            content,
                            iterations,
                            calls,
                            usage,
                            f"structured_output_invalid:{error.code}",
                        )
                if response_content and (response_contract is None or not tool_calls):
                    content = response_content
                    # Text accompanying tool calls is compliant progress, not the final answer.
                    event_kind = (
                        AgentEventKind.MODEL_PROGRESS
                        if has_tool_calls
                        else AgentEventKind.TEXT_DELTA
                    )
                    await self._emit(event_kind, iterations, {"text": response_content})
                if usage.total_tokens > self._budget.max_tokens:
                    return await self._finalize(
                        StopReason.TOKEN_BUDGET_EXHAUSTED,
                        history,
                        content,
                        iterations,
                        calls,
                        usage,
                        started_at,
                        response_contract,
                        requirements,
                    )
                if not tool_calls:
                    return await self._stop(
                        StopReason.COMPLETED,
                        content,
                        iterations,
                        calls,
                        usage,
                        structured_output=structured_output,
                    )

                history.append(
                    Message(
                        Role.ASSISTANT,
                        "" if response_contract is not None else response_content or "",
                        tool_calls=history_tool_calls,
                    )
                )
                prepared_policy_calls: (
                    tuple[tuple[ToolCall, _PolicyExecutionBinding] | None, ...] | None
                ) = None
                if self._policy_engine is not None:
                    # Prevalidate duplicates and reserve every novel call in the response before
                    # authorization: no call may execute if a later member exceeds the budget.
                    budget_keys = set(seen_calls)
                    batch_tool_count = 0
                    for budget_call in tool_calls:
                        budget_key = json.dumps(
                            [budget_call.name, dict(budget_call.arguments)],
                            sort_keys=True,
                            separators=(",", ":"),
                            default=str,
                        )
                        if budget_key not in budget_keys:
                            budget_keys.add(budget_key)
                            batch_tool_count += 1
                    if len(calls) + batch_tool_count > self._budget.max_tool_calls:
                        self._append_unexecuted_tool_results(
                            history, tool_calls, StopReason.TOOL_BUDGET_EXHAUSTED.value
                        )
                        return await self._finalize(
                            StopReason.TOOL_BUDGET_EXHAUSTED,
                            history,
                            content,
                            iterations,
                            calls,
                            usage,
                            started_at,
                            response_contract,
                            requirements,
                        )
                    preparation = await self._prepare_policy_batch(
                        tool_calls,
                        native_bindings,
                        iterations,
                        calls,
                        history,
                        seen_calls,
                        started_at,
                    )
                    if isinstance(preparation, StopReason):
                        return await self._stop(preparation, content, iterations, calls, usage)
                    prepared_policy_calls = preparation
                for call_index, call in enumerate(tool_calls):
                    policy_binding: _PolicyExecutionBinding | None = None
                    if prepared_policy_calls is not None:
                        prepared_call = prepared_policy_calls[call_index]
                        if prepared_call is None:
                            continue
                        execution_call, policy_binding = prepared_call
                    else:
                        if len(calls) >= self._budget.max_tool_calls:
                            self._append_unexecuted_tool_results(
                                history,
                                tool_calls[call_index:],
                                StopReason.TOOL_BUDGET_EXHAUSTED.value,
                            )
                            return await self._finalize(
                                StopReason.TOOL_BUDGET_EXHAUSTED,
                                history,
                                content,
                                iterations,
                                calls,
                                usage,
                                started_at,
                                response_contract,
                                requirements,
                            )
                        call_key = json.dumps(
                            [call.name, dict(call.arguments)],
                            sort_keys=True,
                            separators=(",", ":"),
                            default=str,
                        )
                        if call_key in seen_calls:
                            duplicate = {
                                "error": "Duplicate tool call blocked; use existing result."
                            }
                            history.append(
                                Message(
                                    Role.TOOL,
                                    json.dumps(duplicate, separators=(",", ":")),
                                    tool_call_id=call.id,
                                )
                            )
                            continue
                        seen_calls.add(call_key)
                        await self._emit(
                            AgentEventKind.TOOL_CALL_REQUESTED,
                            iterations,
                            {
                                "id": call.id,
                                "name": call.name,
                                "arguments": copy.deepcopy(dict(call.arguments)),
                            },
                        )
                        execution_call = call
                    # Deprecated compatibility path. It is deliberately unreachable in policy
                    # mode, so a legacy hook cannot bypass or replace policy authorization.
                    if (
                        prepared_policy_calls is None
                        and self._approval_hook
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
                                "tool_call_id": call.id,
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
                    try:
                        output = await self._within_deadline(
                            self._tools.execute(execution_call), started_at
                        )
                    except _RuntimeDeadlineExceededError:
                        raise
                    except Exception as tool_err:
                        # Reflexion: feed error back to the LLM so it can self-correct
                        error_output = {
                            "error": f"{type(tool_err).__name__}: {tool_err}",
                            "reflexion_hint": "The tool call failed. Analyze the error, "
                            "adjust your approach, and try again with corrected parameters "
                            "or a different tool.",
                        }
                        if policy_binding is None:
                            record = {
                                "tool": call.name,
                                "tool_call_id": call.id,
                                "parameters": dict(call.arguments),
                                "result": error_output,
                                "status": "error",
                            }
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
                            record = {
                                "tool": policy_binding.tool_name,
                                "tool_call_id": policy_binding.tool_call_id,
                                "parameters": self._policy_binding_arguments(policy_binding),
                                "result": error_output,
                                "status": "error",
                                **self._policy_tool_result_data(
                                    policy_binding, error_serialized, "error"
                                ),
                            }
                            completed_data = self._policy_tool_result_data(
                                policy_binding,
                                error_serialized,
                                "error",
                            )
                        calls.append(record)
                        await self._emit(
                            AgentEventKind.TOOL_CALL_COMPLETED,
                            iterations,
                            completed_data,
                        )
                        history.append(
                            Message(
                                Role.TOOL,
                                json.dumps(error_output, separators=(",", ":")),
                                tool_call_id=(
                                    call.id
                                    if policy_binding is None
                                    else policy_binding.tool_call_id
                                ),
                            )
                        )
                        continue
                    serialized = json.dumps(
                        output, sort_keys=True, separators=(",", ":"), default=str
                    )
                    execution_status = (
                        "duplicate"
                        if output.get("status") == "duplicate_effect_blocked"
                        else "success"
                    )
                    if policy_binding is None:
                        record = {
                            "tool": call.name,
                            "tool_call_id": call.id,
                            "parameters": dict(call.arguments),
                            "result": dict(output),
                            "status": execution_status,
                        }
                        completed_data = {
                            "id": call.id,
                            "name": call.name,
                            "arguments": dict(call.arguments),
                            "output": dict(output),
                            "status": execution_status,
                        }
                    else:
                        record = {
                            "tool": policy_binding.tool_name,
                            "tool_call_id": policy_binding.tool_call_id,
                            "parameters": self._policy_binding_arguments(policy_binding),
                            "result": dict(output),
                            "status": execution_status,
                            **self._policy_tool_result_data(
                                policy_binding, serialized, execution_status
                            ),
                        }
                        completed_data = self._policy_tool_result_data(
                            policy_binding,
                            serialized,
                            execution_status,
                        )
                    calls.append(record)
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
                    history.append(
                        Message(
                            Role.TOOL,
                            serialized,
                            tool_call_id=(
                                call.id if policy_binding is None else policy_binding.tool_call_id
                            ),
                        )
                    )
            return await self._finalize(
                StopReason.ITERATION_BUDGET_EXHAUSTED,
                history,
                content,
                iterations,
                calls,
                usage,
                started_at,
                response_contract,
                requirements,
            )
        except (TimeoutError, _RuntimeDeadlineExceededError):
            return await self._stop(
                StopReason.TIME_BUDGET_EXHAUSTED, content, iterations, calls, usage
            )
        except (
            ModelBudgetExhausted,
            DuplicateModelCharge,
            IndeterminateModelCharge,
            DurableModelChargeStateError,
        ) as error:
            return await self._stop_for_budget_error(
                error,
                content=content,
                iterations=iterations,
                calls=calls,
                usage=usage,
            )
        except Exception as error:
            return await self._stop(
                StopReason.ERROR,
                content,
                iterations,
                calls,
                usage,
                f"runtime_error:{type(error).__name__}",
            )

    async def _stop_for_budget_error(
        self,
        error: (
            ModelBudgetExhausted
            | DuplicateModelCharge
            | IndeterminateModelCharge
            | DurableModelChargeStateError
        ),
        *,
        content: str,
        iterations: int,
        calls: list[dict[str, Any]],
        usage: TokenUsage,
    ) -> AgentResult:
        if isinstance(error, ModelBudgetExhausted):
            reason = StopReason.MONETARY_BUDGET_EXHAUSTED
        elif isinstance(error, DuplicateModelCharge):
            reason = StopReason.MODEL_CHARGE_DUPLICATE
        else:
            reason = StopReason.MODEL_CHARGE_INDETERMINATE
        await self._emit(
            AgentEventKind.BUDGET_BLOCKED,
            iterations,
            {"code": error.code, "stop_reason": reason.value},
        )
        return await self._stop(
            reason,
            content,
            iterations,
            calls,
            usage,
            error=error.code,
        )

    @staticmethod
    def _provider_requirements(
        messages: Sequence[Message],
        response_contract: ResponseContract | None,
        explicit: ProviderCapabilities | None,
        *,
        native_tools_required: bool = False,
    ) -> ProviderCapabilities:
        explicit = explicit or ProviderCapabilities()
        return ProviderCapabilities(
            native_tools=explicit.native_tools or native_tools_required,
            images=explicit.images or any(message.images for message in messages),
            json_mode=explicit.json_mode or response_contract is not None,
            json_schema=explicit.json_schema,
            prompt_caching=explicit.prompt_caching,
            cache_usage=explicit.cache_usage,
            usage=explicit.usage,
            stop_reason=explicit.stop_reason,
            streaming=explicit.streaming,
        )

    @staticmethod
    def _safe_missing_capability_names(
        error: UnsupportedProviderCapability,
    ) -> tuple[str, ...]:
        """Copy only names from the closed capability vocabulary; never expose provider text."""
        reported = frozenset(error.missing_capabilities)
        return tuple(name for name in ProviderCapabilities.__dataclass_fields__ if name in reported)

    @staticmethod
    def _normalize_provider_stop_reason(
        reason: str | None, has_tool_calls: bool
    ) -> StopReason | None:
        normalized = reason.strip().lower() if reason else ""
        if normalized in {"tool_use", "tool_calls"}:
            return None if has_tool_calls else StopReason.PROVIDER_ERROR
        if normalized in {"", "stop", "end_turn", "stop_sequence", "completed"}:
            return StopReason.COMPLETED
        if normalized in {"max_tokens", "length", "max_output_tokens"}:
            return StopReason.PROVIDER_LENGTH_LIMIT
        if normalized == "refusal":
            return StopReason.PROVIDER_REFUSAL
        if normalized in {"content_filter", "safety", "blocked"}:
            return StopReason.PROVIDER_CONTENT_FILTER
        return StopReason.PROVIDER_ERROR

    async def _reject_provider_capabilities(
        self,
        missing: tuple[str, ...],
        content: str,
        iterations: int,
        calls: list[dict[str, Any]],
        usage: TokenUsage,
    ) -> AgentResult:
        await self._emit(
            AgentEventKind.PROVIDER_CAPABILITY_REJECTED,
            iterations,
            {
                "code": "provider_capability_unsupported",
                "missing_capabilities": missing,
            },
        )
        return await self._stop(
            StopReason.PROVIDER_CAPABILITY_UNSUPPORTED,
            content,
            iterations,
            calls,
            usage,
            f"provider_capability_unsupported:{','.join(missing)}",
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

    async def _prepare_policy_batch(
        self,
        tool_calls: tuple[ToolCall, ...],
        native_bindings: tuple[_NativeToolBinding, ...],
        iteration: int,
        calls: list[dict[str, Any]],
        history: list[Message],
        seen_calls: set[str],
        started_at: float,
    ) -> StopReason | tuple[tuple[ToolCall, _PolicyExecutionBinding] | None, ...]:
        """Authorize and bind an entire provider batch before dispatching any call."""
        prepared: list[tuple[ToolCall, _PolicyExecutionBinding] | None] = []
        batch_seen = set(seen_calls)
        for call, native_binding in zip(tool_calls, native_bindings, strict=True):
            call_key = json.dumps(
                [call.name, dict(call.arguments)],
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            if call_key in batch_seen:
                duplicate = {"error": "Duplicate tool call blocked; use existing result."}
                history.append(
                    Message(
                        Role.TOOL,
                        json.dumps(duplicate, separators=(",", ":")),
                        tool_call_id=call.id,
                    )
                )
                prepared.append(None)
                continue
            batch_seen.add(call_key)
            await self._emit(
                AgentEventKind.TOOL_CALL_REQUESTED,
                iteration,
                {
                    "id": native_binding.tool_call_id,
                    "name": native_binding.tool_name,
                    "arguments_hash": native_binding.arguments_hash,
                },
            )
            enforcement = await self._enforce_policy(
                call, native_binding, iteration, calls, started_at
            )
            if isinstance(enforcement, StopReason):
                return enforcement
            try:
                execution_call = self._prepare_policy_execution_call(call, enforcement)
            except Exception:
                bound_call = ToolCall(enforcement.tool_call_id, enforcement.tool_name)
                reason_code = "binding_mismatch"
                if enforcement.action is PolicyAction.ASK:
                    await self._emit_approval_failure(
                        bound_call, iteration, enforcement.arguments_hash, reason_code
                    )
                    stop_reason = StopReason.APPROVAL_UNAVAILABLE
                else:
                    await self._emit_policy_failure(
                        bound_call, iteration, reason_code, enforcement.arguments_hash
                    )
                    stop_reason = StopReason.POLICY_DENIED
                await self._record_denial(
                    bound_call,
                    iteration,
                    calls,
                    reason_code,
                    enforcement.arguments_hash,
                )
                return stop_reason
            prepared.append((execution_call, enforcement))
        seen_calls.update(batch_seen)
        return tuple(prepared)

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
            # Bind every authorization-relevant value before constructing an event or awaiting
            # any collaborator. PolicyDecision is frozen by convention only: object.__setattr__
            # can still mutate an instance retained by a hostile engine or event sink.
            decision_action = decision.action
            decision_risks = frozenset(decision.risk_classes)
            decision_rule = decision.matched_rule_id
            decision_reason = decision.reason
            if not isinstance(decision_action, PolicyAction):
                raise TypeError("policy decision action is invalid")
            if decision_risks != request.risk_classes:
                raise ValueError("policy decision risk binding mismatch")
            if decision_rule is not None and not isinstance(decision_rule, str):
                raise TypeError("policy decision rule is invalid")
            if not isinstance(decision_reason, str):
                raise TypeError("policy decision reason is invalid")
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
            "action": decision_action.value,
            "reason_code": decision_reason_codes[decision_action],
            "risk_classes": sorted(risk.value for risk in decision_risks),
            "arguments_hash": arguments_hash,
        }
        if decision_rule and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", decision_rule):
            policy_data["matched_rule_id"] = decision_rule
        await self._emit(AgentEventKind.POLICY_DECIDED, iteration, policy_data)

        binding = _PolicyExecutionBinding(
            native_binding.tool_call_id,
            tool_name,
            arguments_hash,
            native_binding.arguments_json,
            request,
            decision_action,
            decision_risks,
            decision_rule,
            decision_reason,
        )
        if decision_action is PolicyAction.ALLOW:
            return binding
        if decision_action is PolicyAction.DENY:
            await self._record_denial(event_call, iteration, calls, "policy_denied", arguments_hash)
            return StopReason.POLICY_DENIED

        if self._authorizer is None:
            await self._record_denial(
                event_call, iteration, calls, "approval_unavailable", arguments_hash
            )
            return StopReason.APPROVAL_UNAVAILABLE

        approval_tool_call_id = native_binding.tool_call_id
        approval_tool_name = tool_name
        approval_arguments_hash = arguments_hash
        approval_risk_classes = decision_risks
        approval_matched_rule_id = decision_rule
        authorization_request = AuthorizationRequest(
            tool_call_id=approval_tool_call_id,
            tool_name=approval_tool_name,
            arguments_hash=approval_arguments_hash,
            risk_classes=approval_risk_classes,
            matched_rule_id=approval_matched_rule_id,
        )
        cleanup_request = AuthorizationRequest(
            tool_call_id=approval_tool_call_id,
            tool_name=approval_tool_name,
            arguments_hash=approval_arguments_hash,
            risk_classes=approval_risk_classes,
            matched_rule_id=approval_matched_rule_id,
        )
        approval_data = {
            "id": native_binding.tool_call_id,
            "name": tool_name,
            "arguments_hash": arguments_hash,
            "risk_classes": sorted(risk.value for risk in decision_risks),
        }
        preparatory_authorizer = (
            self._authorizer if isinstance(self._authorizer, PreparatoryToolAuthorizer) else None
        )
        if preparatory_authorizer is not None:
            try:
                await preparatory_authorizer.prepare(authorization_request)
            except asyncio.CancelledError:
                await preparatory_authorizer.cancel(cleanup_request)
                raise
            except Exception:
                await preparatory_authorizer.cancel(cleanup_request)
                await self._emit_approval_failure(
                    event_call, iteration, arguments_hash, "approval_unavailable"
                )
                await self._record_denial(
                    event_call, iteration, calls, "approval_unavailable", arguments_hash
                )
                return StopReason.APPROVAL_UNAVAILABLE
            if self._expired(started_at):
                raise DeadlineExceededError
            if authorization_request != cleanup_request:
                await preparatory_authorizer.cancel(cleanup_request)
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
        try:
            await self._emit(AgentEventKind.APPROVAL_REQUIRED, iteration, approval_data)
        except BaseException:
            if preparatory_authorizer is not None:
                await preparatory_authorizer.cancel(cleanup_request)
            raise

        runtime_remaining = self._budget.max_seconds - (self._clock() - started_at)
        timeout = min(runtime_remaining, self._approval_timeout_seconds)
        if timeout <= 0:
            if preparatory_authorizer is not None:
                await preparatory_authorizer.cancel(cleanup_request)
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
                authorization_task.add_done_callback(consume_detached_task)
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
                authorization_task.add_done_callback(consume_detached_task)
            raise
        except Exception:
            await self._emit_approval_failure(
                event_call, iteration, arguments_hash, "approval_unavailable"
            )
            await self._record_denial(
                event_call, iteration, calls, "approval_unavailable", arguments_hash
            )
            return StopReason.APPROVAL_UNAVAILABLE
        finally:
            if preparatory_authorizer is not None:
                with suppress(Exception):
                    await preparatory_authorizer.cancel(cleanup_request)

        # The authorizer owns both references while authorize() runs and may retain the
        # outcome after returning it. Validate and copy every decision scalar before the
        # next await; neither audit emission nor dispatch may consult that object again.
        try:
            request_binding_matches = (
                authorization_request.tool_call_id == approval_tool_call_id
                and authorization_request.tool_name == approval_tool_name
                and authorization_request.arguments_hash == approval_arguments_hash
                and authorization_request.risk_classes == approval_risk_classes
                and authorization_request.matched_rule_id == approval_matched_rule_id
            )
            if not isinstance(outcome, AuthorizationOutcome):
                raise TypeError("authorizer returned an invalid outcome")
            outcome_approved = outcome.approved
            outcome_tool_call_id = outcome.tool_call_id
            outcome_tool_name = outcome.tool_name
            outcome_arguments_hash = outcome.arguments_hash
            outcome_reason_code = outcome.reason_code
            if type(outcome_approved) is not bool:
                raise TypeError("authorization approved value is invalid")
            if not isinstance(outcome_tool_call_id, str):
                raise TypeError("authorization tool call id is invalid")
            if not isinstance(outcome_tool_name, str):
                raise TypeError("authorization tool name is invalid")
            if not isinstance(outcome_arguments_hash, str):
                raise TypeError("authorization arguments hash is invalid")
            if not isinstance(outcome_reason_code, str) or not re.fullmatch(
                r"[a-z][a-z0-9_]{0,63}", outcome_reason_code
            ):
                raise ValueError("authorization reason code is invalid")
            outcome_binding_matches = (
                outcome_tool_call_id == approval_tool_call_id
                and outcome_tool_name == approval_tool_name
                and outcome_arguments_hash == approval_arguments_hash
            )
            authorization_decision = _AuthorizationDecisionBinding(
                outcome_approved,
                outcome_tool_call_id,
                outcome_tool_name,
                outcome_arguments_hash,
                outcome_reason_code,
            )
        except Exception:
            request_binding_matches = False
            outcome_binding_matches = False
            authorization_decision = None
        if (
            not request_binding_matches
            or not outcome_binding_matches
            or authorization_decision is None
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
                "id": authorization_decision.tool_call_id,
                "name": authorization_decision.tool_name,
                "arguments_hash": authorization_decision.arguments_hash,
                "approved": authorization_decision.approved,
                "reason_code": authorization_decision.reason_code,
            },
        )
        if authorization_decision.approved:
            return binding
        await self._record_denial(
            event_call,
            iteration,
            calls,
            authorization_decision.reason_code,
            authorization_decision.arguments_hash,
        )
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
    def _policy_binding_arguments(binding: _PolicyExecutionBinding) -> dict[str, Any]:
        """Return a fresh canonical argument snapshot from the pre-dispatch binding."""
        return canonical_arguments_snapshot(json.loads(binding.arguments_json))

    @staticmethod
    def _policy_tool_result_data(
        binding: _PolicyExecutionBinding, serialized_output: str, status: str
    ) -> dict[str, Any]:
        encoded = serialized_output.encode("utf-8")
        return {
            "id": binding.tool_call_id,
            "name": binding.tool_name,
            "arguments_hash": binding.arguments_hash,
            "arguments_size": len(binding.arguments_json.encode("utf-8")),
            "output_hash": hashlib.sha256(encoded).hexdigest(),
            "output_size": len(encoded),
            "status": status,
        }

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

    @staticmethod
    def _append_unexecuted_tool_results(
        history: list[Message], tool_calls: Sequence[ToolCall], reason_code: str
    ) -> None:
        """Close provider tool-use blocks without executing calls that exceeded a budget."""

        for call in tool_calls:
            history.append(
                Message(
                    Role.TOOL,
                    json.dumps(
                        {
                            "error": "Tool call was not executed.",
                            "reason_code": reason_code,
                        },
                        separators=(",", ":"),
                    ),
                    tool_call_id=call.id,
                )
            )

    async def _finalize(
        self,
        reason: StopReason,
        history: list[Message],
        content: str,
        iterations: int,
        calls: list[dict[str, Any]],
        usage: TokenUsage,
        started_at: float,
        response_contract: ResponseContract | None,
        requirements: ProviderCapabilities,
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
        missing_capabilities = get_provider_capabilities(self._model).missing(requirements)
        if missing_capabilities:
            return await self._reject_provider_capabilities(
                missing_capabilities, content, iterations, calls, usage
            )
        try:
            provider_kwargs: dict[str, Any] = {"max_tokens": self._budget.final_synthesis_tokens}
            if response_contract is not None:
                provider_kwargs["response_contract"] = response_contract
            if inspect.getattr_static(self._model, "routes_capabilities", False) is True:
                provider_kwargs["required_capabilities"] = requirements
            response = await self._within_deadline(
                self._model.complete(
                    self._snapshot_history(history),
                    (),
                    **provider_kwargs,
                ),
                started_at,
            )
            response_content = response.content if isinstance(response.content, str) else None
            has_final_tool_calls = bool(response.tool_calls)
            raw_stop_reason = response.provider_stop_reason
            provider_stop_reason = raw_stop_reason if isinstance(raw_stop_reason, str) else None
            response_usage = TokenUsage(
                response.usage.input_tokens,
                response.usage.output_tokens,
                response.usage.cache_read_input_tokens,
                response.usage.cache_write_input_tokens,
            )
            usage += response_usage
            response_event_data: dict[str, Any] = {}
            if provider_stop_reason is not None:
                response_event_data["provider_stop_reason"] = provider_stop_reason
            raw_actual_provider = getattr(response, "actual_provider", None)
            if isinstance(raw_actual_provider, str):
                response_event_data["actual_provider"] = raw_actual_provider
            raw_actual_model = getattr(response, "actual_model", None)
            if isinstance(raw_actual_model, str):
                response_event_data["actual_model"] = raw_actual_model
            await self._emit(
                AgentEventKind.MODEL_RESPONSE,
                iterations,
                response_event_data,
                response_usage,
            )
            provider_reason = self._normalize_provider_stop_reason(
                provider_stop_reason, has_tool_calls=False
            )
            if provider_reason not in (None, StopReason.COMPLETED):
                return await self._stop(
                    provider_reason,
                    content,
                    iterations,
                    calls,
                    usage,
                    f"provider_stop_reason:{provider_reason.value}",
                )
            if has_final_tool_calls:
                return await self._stop(
                    StopReason.PROVIDER_ERROR,
                    content,
                    iterations,
                    calls,
                    usage,
                    "provider_stop_reason:final_synthesis_tool_call",
                )
            if response_content and self._compliance is not None:
                response_content = self._compliance.enforce_output(response_content)
            structured_output: object | None = None
            if response_contract is not None:
                try:
                    structured_output = response_contract.parse_and_validate(response_content or "")
                except StructuredOutputError as error:
                    await self._emit(
                        AgentEventKind.STRUCTURED_OUTPUT_REJECTED,
                        iterations,
                        {"code": error.code},
                    )
                    return await self._stop(
                        StopReason.STRUCTURED_OUTPUT_INVALID,
                        content,
                        iterations,
                        calls,
                        usage,
                        f"structured_output_invalid:{error.code}",
                    )
            if response_content:
                content = response_content
                await self._emit(AgentEventKind.TEXT_DELTA, iterations, {"text": content})
            return await self._stop(
                reason,
                content,
                iterations,
                calls,
                usage,
                structured_output=structured_output,
            )
        except _RuntimeDeadlineExceededError:
            return await self._stop(
                StopReason.TIME_BUDGET_EXHAUSTED, content, iterations, calls, usage
            )
        except (
            ModelBudgetExhausted,
            DuplicateModelCharge,
            IndeterminateModelCharge,
            DurableModelChargeStateError,
        ) as error:
            return await self._stop_for_budget_error(
                error,
                content=content,
                iterations=iterations,
                calls=calls,
                usage=usage,
            )
        except UnsupportedProviderCapability as error:
            return await self._reject_provider_capabilities(
                self._safe_missing_capability_names(error),
                content,
                iterations,
                calls,
                usage,
            )
        except Exception as error:
            logger.warning(
                "final_synthesis_failed",
                stop_reason=reason.value,
                error_type=type(error).__name__,
            )
            return await self._stop(
                reason,
                content,
                iterations,
                calls,
                usage,
                error="final_synthesis_failed",
            )

    async def _deadline_result(self, state: _RuntimeDeadlineState) -> AgentResult:
        """Return promptly and attempt terminal persistence on a separate short budget."""

        usage = state.usage or TokenUsage()
        if state.terminal_started:
            if state.terminal_task is not None and not state.terminal_task.done():

                async def wait_for_existing_terminal() -> None:
                    await asyncio.shield(state.terminal_task)

                with suppress(BaseException):
                    await await_before_deadline(
                        wait_for_existing_terminal(),
                        deadline=time.monotonic() + _RUNTIME_TERMINAL_CLEANUP_SECONDS,
                        clock=time.monotonic,
                    )
                if not state.terminal_task.done():
                    state.terminal_task.cancel()
                    with suppress(BaseException):
                        await await_before_deadline(
                            wait_for_existing_terminal(),
                            deadline=time.monotonic() + _RUNTIME_TERMINAL_CLEANUP_SECONDS,
                            clock=time.monotonic,
                        )
            error = state.terminal_error
            if not state.terminal_persisted:
                logger.warning(
                    "runtime_terminal_persistence_indeterminate",
                    error_type="deadline_interrupted",
                    stop_reason=(state.terminal_reason or StopReason.TIME_BUDGET_EXHAUSTED).value,
                )
                error = error or "terminal_persistence_indeterminate"
            return AgentResult(
                state.content,
                state.terminal_reason or StopReason.TIME_BUDGET_EXHAUSTED,
                state.iterations,
                state.calls,
                usage,
                error,
                state.structured_output,
            )

        try:
            return await await_before_deadline(
                self._stop(
                    StopReason.TIME_BUDGET_EXHAUSTED,
                    state.content,
                    state.iterations,
                    [dict(item) for item in state.calls],
                    usage,
                    "deadline_exceeded",
                ),
                deadline=time.monotonic() + _RUNTIME_TERMINAL_CLEANUP_SECONDS,
                clock=time.monotonic,
            )
        except BaseException as error:
            logger.warning(
                "runtime_terminal_persistence_indeterminate",
                error_type=type(error).__name__,
                stop_reason=StopReason.TIME_BUDGET_EXHAUSTED.value,
            )
            return AgentResult(
                state.content,
                StopReason.TIME_BUDGET_EXHAUSTED,
                state.iterations,
                state.calls,
                usage,
                "terminal_persistence_indeterminate",
            )

    def _expired(self, started_at: float) -> bool:
        return self._clock() - started_at >= self._budget.max_seconds

    async def _within_deadline(self, awaitable: Coroutine[Any, Any, T], started_at: float) -> T:
        return await await_before_deadline(
            awaitable,
            deadline=started_at + self._budget.max_seconds,
            clock=self._clock,
        )

    async def _emit(
        self,
        kind: AgentEventKind,
        iteration: int,
        data: dict[str, Any] | None = None,
        usage: TokenUsage | None = None,
    ) -> None:
        event_usage = usage or TokenUsage()
        event_data = dict(data or {})
        if kind in (AgentEventKind.MODEL_RESPONSE, AgentEventKind.RUN_STOPPED):
            if event_usage.cache_read_input_tokens is not None:
                event_data["cache_read_input_tokens"] = event_usage.cache_read_input_tokens
            if event_usage.cache_write_input_tokens is not None:
                event_data["cache_write_input_tokens"] = event_usage.cache_write_input_tokens
        await self._events.emit(AgentEvent(kind, iteration, event_data, event_usage))
        state = _RUNTIME_DEADLINE_STATE.get()
        if state is not None:
            if kind is AgentEventKind.RUN_STOPPED:
                state.terminal_persisted = True
            elif self._clock() >= state.deadline:
                raise DeadlineExceededError

    async def _stop(
        self,
        reason: StopReason,
        content: str,
        iterations: int,
        calls: list[dict[str, Any]],
        usage: TokenUsage,
        error: str | None = None,
        structured_output: object | None = None,
    ) -> AgentResult:
        # The terminal event finalizes completed_at, so persist the compliant final answer first.
        if self._compliance is not None:
            content = self._compliance.enforce_output(content)
        state = _RUNTIME_DEADLINE_STATE.get()
        terminal_task: asyncio.Task[None] | None = None
        if state is not None:
            if state.terminal_started:
                reason = state.terminal_reason or reason
                error = state.terminal_error
                structured_output = state.structured_output
                content = state.content
                iterations = state.iterations
                calls = [dict(item) for item in state.calls]
                usage = state.usage or usage
                terminal_task = state.terminal_task
            else:
                state.terminal_started = True
                state.terminal_reason = reason
                state.terminal_error = error
                state.structured_output = structured_output
                state.content = content
                state.iterations = iterations
                state.calls = tuple(calls)
                state.usage = usage

        async def persist_terminal() -> None:
            if self._result_recorder is not None:
                await self._result_recorder(content)
            await self._emit(
                AgentEventKind.RUN_STOPPED,
                iterations,
                {"reason": reason.value, "error": error},
                usage,
            )

        if terminal_task is None:
            terminal_task = asyncio.create_task(persist_terminal())
            terminal_task.add_done_callback(consume_detached_task)
            if state is not None:
                state.terminal_task = terminal_task
        await asyncio.shield(terminal_task)
        if state is not None:
            state.terminal_persisted = True
        return AgentResult(
            content, reason, iterations, tuple(calls), usage, error, structured_output
        )
