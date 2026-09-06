"""Bounded hybrid-orchestration contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from app.runtime.models import Message, TokenUsage

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ExecutionMode(StrEnum):
    AUTO = "auto"
    SINGLE = "single"
    TEAM = "team"


class SpecialistKind(StrEnum):
    FIXED = "fixed"
    DYNAMIC = "dynamic"


class ChildStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    DENIED = "denied"


@dataclass(frozen=True, slots=True)
class OrchestrationDecision:
    requested_mode: ExecutionMode
    resolved_mode: ExecutionMode
    reason_code: str
    router_version: str = "hybrid-router-v2"
    degraded: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.requested_mode, ExecutionMode):
            object.__setattr__(self, "requested_mode", ExecutionMode(self.requested_mode))
        if not isinstance(self.resolved_mode, ExecutionMode):
            object.__setattr__(self, "resolved_mode", ExecutionMode(self.resolved_mode))
        if self.resolved_mode is ExecutionMode.AUTO:
            raise ValueError("resolved mode cannot remain auto")
        if _SAFE_ID.fullmatch(self.reason_code) is None:
            raise ValueError("reason_code must be a safe identifier")


@dataclass(frozen=True, slots=True)
class ChildTask:
    child_run_id: str
    profile_id: str
    kind: SpecialistKind
    goal: str
    system_prompt: str
    allowed_tools: tuple[str, ...]
    max_iterations: int = 4
    max_tool_calls: int = 6
    max_tokens: int = 64_000
    max_tool_result_chars: int = 3_000
    timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        if _SAFE_ID.fullmatch(self.child_run_id) is None:
            raise ValueError("child_run_id must be a safe identifier")
        if _SAFE_ID.fullmatch(self.profile_id) is None:
            raise ValueError("profile_id must be a safe identifier")
        if not isinstance(self.kind, SpecialistKind):
            object.__setattr__(self, "kind", SpecialistKind(self.kind))
        if not self.goal or len(self.goal) > 10_000:
            raise ValueError("goal must be non-empty and bounded")
        if not self.system_prompt or len(self.system_prompt) > 8_000:
            raise ValueError("system_prompt must be non-empty and bounded")
        if not self.allowed_tools or len(self.allowed_tools) > 16:
            raise ValueError("allowed_tools must be non-empty and bounded")
        if len(set(self.allowed_tools)) != len(self.allowed_tools):
            raise ValueError("allowed_tools must be unique")
        if not 1 <= self.max_iterations <= 8:
            raise ValueError("max_iterations is outside pilot bounds")
        if not 0 <= self.max_tool_calls <= 12:
            raise ValueError("max_tool_calls is outside pilot bounds")
        if not 1 <= self.max_tokens <= 64_000:
            raise ValueError("max_tokens is outside pilot bounds")
        if not 500 <= self.max_tool_result_chars <= 12_000:
            raise ValueError("max_tool_result_chars is outside pilot bounds")
        if not 1.0 <= self.timeout_seconds <= 120.0:
            raise ValueError("timeout_seconds is outside pilot bounds")


@dataclass(frozen=True, slots=True)
class DelegationPlan:
    plan_id: str
    tasks: tuple[ChildTask, ...]
    max_parallelism: int = 1

    def __post_init__(self) -> None:
        if _SAFE_ID.fullmatch(self.plan_id) is None:
            raise ValueError("plan_id must be a safe identifier")
        if not 1 <= len(self.tasks) <= 3:
            raise ValueError("plan must contain between one and three tasks")
        if len({task.child_run_id for task in self.tasks}) != len(self.tasks):
            raise ValueError("child run IDs must be unique")
        if not 1 <= self.max_parallelism <= len(self.tasks):
            raise ValueError("max_parallelism is outside plan bounds")


@dataclass(frozen=True, slots=True)
class ChildResult:
    child_run_id: str
    profile_id: str
    kind: SpecialistKind
    status: ChildStatus
    content: str
    usage: TokenUsage
    iterations: int
    tool_calls: tuple[dict, ...]
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SpecialistKind):
            object.__setattr__(self, "kind", SpecialistKind(self.kind))
        if not isinstance(self.status, ChildStatus):
            object.__setattr__(self, "status", ChildStatus(self.status))
        if len(self.content) > 12_000:
            raise ValueError("child content exceeds synthesis bound")
        if self.iterations < 0:
            raise ValueError("iterations cannot be negative")


@dataclass(frozen=True, slots=True)
class OrchestrationOutcome:
    decision: OrchestrationDecision
    messages: tuple[Message, ...]
    children: tuple[ChildResult, ...] = ()
    degraded: bool = False
