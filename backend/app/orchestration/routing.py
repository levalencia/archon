"""Deterministic routing policy for the hybrid orchestration pilot."""

from __future__ import annotations

import re

from app.orchestration.models import ExecutionMode, OrchestrationDecision

_TEAM_SIGNALS = (
    "analy",
    "architect",
    "audit",
    "compare",
    "compar",
    "evaluate",
    "evalua",
    "evidence",
    "investig",
    "research",
    "review",
    "revis",
    "security",
    "sources",
    "trade-off",
    "tradeoff",
    "verify",
    "verific",
)


def resolve_execution_mode(
    query: str,
    requested_mode: ExecutionMode | str,
    *,
    enabled: bool,
) -> OrchestrationDecision:
    """Resolve a request without an extra model call.

    Auto routing is deliberately conservative: uncertain requests stay on the
    proven single-agent path. The closed reason codes are safe to persist.
    """

    mode = (
        requested_mode
        if isinstance(requested_mode, ExecutionMode)
        else ExecutionMode(requested_mode)
    )
    if not enabled:
        return OrchestrationDecision(
            mode,
            ExecutionMode.SINGLE,
            "feature_disabled",
            degraded=mode is ExecutionMode.TEAM,
        )
    if mode is ExecutionMode.SINGLE:
        return OrchestrationDecision(mode, ExecutionMode.SINGLE, "user_forced_single")
    if mode is ExecutionMode.TEAM:
        return OrchestrationDecision(mode, ExecutionMode.TEAM, "user_forced_team")

    normalized = " ".join(query.casefold().split())
    words = re.findall(r"[\w-]+", normalized)
    signal_count = sum(1 for signal in _TEAM_SIGNALS if signal in normalized)
    if len(words) >= 28 or signal_count >= 2:
        return OrchestrationDecision(mode, ExecutionMode.TEAM, "cross_domain_task")
    return OrchestrationDecision(mode, ExecutionMode.SINGLE, "simple_single_step")
