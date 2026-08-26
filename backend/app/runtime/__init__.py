"""Typed runtime API."""

from app.runtime.engine import AgentResult, AgentRuntime, ApprovalHook, RuntimeBudget, StopReason
from app.runtime.events import AgentEvent, AgentEventKind, EventSink, RecordingEventSink
from app.runtime.models import Message, ModelResponse, Role, TokenUsage, ToolCall, ToolDefinition
from app.runtime.ports import PreparatoryToolAuthorizer, ToolAuthorizer
from app.security.approvals import AuthorizationOutcome, AuthorizationRequest

__all__ = [
    "AgentEvent",
    "AgentEventKind",
    "AgentResult",
    "AgentRuntime",
    "ApprovalHook",
    "AuthorizationOutcome",
    "AuthorizationRequest",
    "EventSink",
    "Message",
    "ModelResponse",
    "PreparatoryToolAuthorizer",
    "RecordingEventSink",
    "Role",
    "RuntimeBudget",
    "StopReason",
    "TokenUsage",
    "ToolAuthorizer",
    "ToolCall",
    "ToolDefinition",
]
