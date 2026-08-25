"""Budgeted, provider-neutral, event-driven agent loop."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Coroutine, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeVar

from app.runtime.events import AgentEvent, AgentEventKind, EventSink, NullEventSink
from app.runtime.models import Message, Role, TokenUsage
from app.runtime.ports import ModelProvider, ToolExecutor

T = TypeVar("T")
Clock = Callable[[], float]

# Approval hook: (tool_name, tool_call_id, arguments) -> approved?
ApprovalHook = Callable[[str, str, dict], Coroutine[Any, Any, bool]]


class StopReason(StrEnum):
    COMPLETED = "completed"
    ITERATION_BUDGET_EXHAUSTED = "iteration_budget_exhausted"
    TOOL_BUDGET_EXHAUSTED = "tool_budget_exhausted"
    TOKEN_BUDGET_EXHAUSTED = "token_budget_exhausted"
    TIME_BUDGET_EXHAUSTED = "time_budget_exhausted"
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
    ) -> None:
        self._model = model
        self._tools = tools
        self._events = events or NullEventSink()
        self._budget = budget or RuntimeBudget()
        self._clock = clock
        self._approval_hook = approval_hook

    async def run(self, messages: Sequence[Message]) -> AgentResult:
        history = list(messages)
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
                response = await self._within_deadline(
                    self._model.complete(
                        history, self._tools.definitions(), max_tokens=min(4096, remaining_tokens)
                    ),
                    started_at,
                )
                usage += response.usage
                if response.content:
                    content = response.content
                await self._emit(
                    AgentEventKind.MODEL_RESPONSE,
                    iterations,
                    {"provider_stop_reason": response.provider_stop_reason},
                    response.usage,
                )
                if response.content:
                    # Text accompanying tool calls is progress, not the final answer.
                    event_kind = (
                        AgentEventKind.MODEL_PROGRESS
                        if response.tool_calls
                        else AgentEventKind.TEXT_DELTA
                    )
                    await self._emit(event_kind, iterations, {"text": response.content})
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
                if not response.tool_calls:
                    return await self._stop(StopReason.COMPLETED, content, iterations, calls, usage)

                history.append(
                    Message(Role.ASSISTANT, response.content or "", tool_calls=response.tool_calls)
                )
                for call in response.tool_calls:
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
                    await self._emit(
                        AgentEventKind.TOOL_CALL_REQUESTED,
                        iterations,
                        {"id": call.id, "name": call.name, "arguments": dict(call.arguments)},
                    )
                    # Human-in-the-loop: check if tool requires approval
                    if self._approval_hook and hasattr(self._tools, "tool_requires_approval") and self._tools.tool_requires_approval(call.name):
                        await self._emit(
                            AgentEventKind.APPROVAL_REQUIRED,
                            iterations,
                            {"id": call.id, "name": call.name, "arguments": dict(call.arguments)},
                        )
                        approved = await self._approval_hook(call.name, call.id, dict(call.arguments))
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
                                {"id": call.id, "name": call.name, "arguments": dict(call.arguments)},
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
                        await self._emit(
                            AgentEventKind.TOOL_CALL_COMPLETED,
                            iterations,
                            {
                                "id": call.id,
                                "name": call.name,
                                "arguments": dict(call.arguments),
                                "output": error_output,
                            },
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
                    await self._emit(
                        AgentEventKind.TOOL_CALL_COMPLETED,
                        iterations,
                        {
                            "id": call.id,
                            "name": call.name,
                            "arguments": dict(call.arguments),
                            "output": dict(output),
                        },
                    )
                    serialized = json.dumps(
                        output, sort_keys=True, separators=(",", ":"), default=str
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
                    history,
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
