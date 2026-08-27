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
    PROVIDER_CAPABILITY_REJECTED = "provider_capability_rejected"
    STRUCTURED_OUTPUT_REJECTED = "structured_output_rejected"
    MODEL_PROGRESS = "model_progress"
    TEXT_DELTA = "text_delta"
    TOOL_CALL_REQUESTED = "tool_call_requested"
    POLICY_DECIDED = "policy_decided"
    TOOL_CALL_COMPLETED = "tool_call_completed"
    TOOL_PROGRESS = "tool_progress"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_DECIDED = "approval_decided"
    TOOL_DENIED = "tool_denied"
    EVIDENCE_RETRIEVED = "evidence_retrieved"
    CLAIM_VERIFIED = "claim_verified"
    GROUNDED_ANSWER = "grounded_answer"
    DELEGATION_REQUESTED = "delegation_requested"
    DELEGATION_COMPLETED = "delegation_completed"
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
