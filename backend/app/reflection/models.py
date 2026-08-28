"""Strict contracts for bounded, final-answer self-reflection."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from app.runtime.models import TokenUsage

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_EVIDENCE_REF = re.compile(r"^(?:request|draft):L[1-9][0-9]{0,5}$")
MAX_ISSUES = 16
MAX_EVIDENCE_REFS = 32


class ReflectionDecision(StrEnum):
    KEEP = "keep"
    REVISE = "revise"


class ReflectionIssueCode(StrEnum):
    FACTUAL_ERROR = "factual_error"
    INSTRUCTION_MISS = "instruction_miss"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    INCOMPLETE = "incomplete"
    UNCLEAR = "unclear"
    SAFETY = "safety"


class ReflectionOutcomeCode(StrEnum):
    KEPT = "kept"
    REVISED = "revised"
    INVALID_VERDICT = "invalid_verdict"
    PROVIDER_ERROR = "provider_error"
    TIME_LIMIT = "time_limit"
    TOKEN_LIMIT = "token_limit"
    COST_LIMIT = "cost_limit"
    TOOL_CALL_BLOCKED = "tool_call_blocked"
    EMPTY_REVISION = "empty_revision"


@dataclass(frozen=True, slots=True)
class ReflectionPolicy:
    """Opt-in hard limits. Reflection always performs at most one revision."""

    enabled: bool = False
    rubric_id: str = "final-answer-quality"
    rubric_version: str = "1"
    max_revisions: int = 1
    max_input_tokens: int = 8_192
    max_output_tokens: int = 2_048
    max_seconds: float = 10.0
    max_cost_usd: Decimal = Decimal("0.05")
    input_cost_per_million_usd: Decimal = Decimal("0")
    output_cost_per_million_usd: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        for value, name in ((self.rubric_id, "rubric_id"), (self.rubric_version, "rubric_version")):
            if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
                raise ValueError(f"{name} must be a safe identifier")
        if type(self.max_revisions) is not int or self.max_revisions not in (0, 1):
            raise ValueError("max_revisions must be zero or one")
        if type(self.max_input_tokens) is not int or not 1 <= self.max_input_tokens <= 65_536:
            raise ValueError("max_input_tokens is outside supported bounds")
        if type(self.max_output_tokens) is not int or not 1 <= self.max_output_tokens <= 16_384:
            raise ValueError("max_output_tokens is outside supported bounds")
        if (
            isinstance(self.max_seconds, bool)
            or not isinstance(self.max_seconds, (int, float))
            or not math.isfinite(float(self.max_seconds))
            or not 0.05 <= float(self.max_seconds) <= 60.0
        ):
            raise ValueError("max_seconds is outside supported bounds")
        object.__setattr__(self, "max_seconds", float(self.max_seconds))
        for name in (
            "max_cost_usd",
            "input_cost_per_million_usd",
            "output_cost_per_million_usd",
        ):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError(f"{name} must be a finite non-negative Decimal")
        if (
            self.enabled
            and self.max_cost_usd > 0
            and self.input_cost_per_million_usd == 0
            and self.output_cost_per_million_usd == 0
        ):
            raise ValueError("enabled reflection requires pricing for a positive cost cap")


@dataclass(frozen=True, slots=True)
class ReflectionVerdict:
    decision: ReflectionDecision
    issue_codes: tuple[ReflectionIssueCode, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    confidence: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.decision, ReflectionDecision):
            object.__setattr__(self, "decision", ReflectionDecision(self.decision))
        codes = tuple(
            item if isinstance(item, ReflectionIssueCode) else ReflectionIssueCode(item)
            for item in self.issue_codes
        )
        if len(codes) > MAX_ISSUES or len(codes) != len(set(codes)):
            raise ValueError("issue_codes must be unique and bounded")
        if self.decision is ReflectionDecision.KEEP and codes:
            raise ValueError("keep verdicts cannot contain issue codes")
        if self.decision is ReflectionDecision.REVISE and not codes:
            raise ValueError("revise verdicts require an issue code")
        refs = tuple(self.evidence_refs)
        if (
            len(refs) > MAX_EVIDENCE_REFS
            or len(refs) != len(set(refs))
            or any(not isinstance(item, str) or _EVIDENCE_REF.fullmatch(item) is None for item in refs)
        ):
            raise ValueError("evidence_refs must be unique bounded request:L# or draft:L# locations")
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not math.isfinite(float(self.confidence))
            or not 0.0 <= float(self.confidence) <= 1.0
        ):
            raise ValueError("confidence must be finite and between zero and one")
        object.__setattr__(self, "issue_codes", codes)
        object.__setattr__(self, "evidence_refs", refs)
        object.__setattr__(self, "confidence", float(self.confidence))


@dataclass(frozen=True, slots=True)
class ReflectionResult:
    content: str
    verdict: ReflectionVerdict | None
    outcome: ReflectionOutcomeCode
    usage: TokenUsage = field(default_factory=TokenUsage)
    calls: int = 0
    revisions: int = 0
    cost_usd: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.calls not in (0, 1, 2) or self.revisions not in (0, 1):
            raise ValueError("reflection call counts are outside hard bounds")
        if self.revisions > self.calls:
            raise ValueError("revision count cannot exceed calls")
