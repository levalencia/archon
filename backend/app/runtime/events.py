"""Events emitted directly by the runtime to HTTP and observability adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from app.runtime.models import TokenUsage


class AgentEventKind(StrEnum):
    RUN_STARTED = "run_started"
    ITERATION_STARTED = "iteration_started"
    MODEL_RESPONSE = "model_response"
    TEXT_DELTA = "text_delta"
    TOOL_CALL_REQUESTED = "tool_call_requested"
    TOOL_CALL_COMPLETED = "tool_call_completed"
    RUN_STOPPED = "run_stopped"


@dataclass(frozen=True, slots=True)
class AgentEvent:
    kind: AgentEventKind
    iteration: int
    data: Mapping[str, Any] = field(default_factory=dict)
    usage: TokenUsage = field(default_factory=TokenUsage)


class EventSink(Protocol):
    async def emit(self, event: AgentEvent) -> None: ...


class NullEventSink:
    async def emit(self, event: AgentEvent) -> None:
        del event


class RecordingEventSink:
    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    async def emit(self, event: AgentEvent) -> None:
        self.events.append(event)
