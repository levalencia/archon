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
    max_tokens: int = 16_000
    max_seconds: float = 90.0

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
    ) -> None:
        self._model = model
        self._tools = tools
        self._events = events or NullEventSink()
        self._budget = budget or RuntimeBudget()
        self._clock = clock

    async def run(self, messages: Sequence[Message]) -> AgentResult:
        history = list(messages)
        started_at = self._clock()
        iterations = 0
        calls: list[dict[str, Any]] = []
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
                    # Adapters currently return complete text. This is an explicit fallback event;
                    # provider-level token streaming can emit multiple TEXT_DELTA events later.
                    await self._emit(
                        AgentEventKind.TEXT_DELTA, iterations, {"text": response.content}
                    )
                if usage.total_tokens > self._budget.max_tokens:
                    return await self._stop(
                        StopReason.TOKEN_BUDGET_EXHAUSTED, content, iterations, calls, usage
                    )
                if not response.tool_calls:
                    return await self._stop(StopReason.COMPLETED, content, iterations, calls, usage)

                history.append(
                    Message(Role.ASSISTANT, response.content or "", tool_calls=response.tool_calls)
                )
                for call in response.tool_calls:
                    if len(calls) >= self._budget.max_tool_calls:
                        return await self._stop(
                            StopReason.TOOL_BUDGET_EXHAUSTED, content, iterations, calls, usage
                        )
                    await self._emit(
                        AgentEventKind.TOOL_CALL_REQUESTED,
                        iterations,
                        {"id": call.id, "name": call.name, "arguments": dict(call.arguments)},
                    )
                    output = await self._within_deadline(self._tools.execute(call), started_at)
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
                        {"id": call.id, "name": call.name, "output": dict(output)},
                    )
                    history.append(
                        Message(
                            Role.TOOL,
                            json.dumps(output, sort_keys=True, separators=(",", ":"), default=str),
                            tool_call_id=call.id,
                        )
                    )
            return await self._stop(
                StopReason.ITERATION_BUDGET_EXHAUSTED, content, iterations, calls, usage
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
