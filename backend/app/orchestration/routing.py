"""Deterministic routing policy for the hybrid orchestration pilot."""

from __future__ import annotations

from app.orchestration.models import ExecutionMode, OrchestrationDecision

_SECURITY_RISK_SIGNALS = (
    "attack",
    "blast radius",
    "defense-in-depth",
    "exfiltration",
    "hipaa",
    "incident",
    "isolation",
    "lateral movement",
    "prompt injection",
    "stride",
    "supply-chain",
    "threat",
    "vulnerab",
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
    risk_signal_count = sum(1 for signal in _SECURITY_RISK_SIGNALS if signal in normalized)
    if risk_signal_count >= 2:
        return OrchestrationDecision(mode, ExecutionMode.TEAM, "security_risk_analysis")
    reason = (
        "insufficient_team_evidence"
        if risk_signal_count == 1 or "security" in normalized
        else "single_default"
    )
    return OrchestrationDecision(mode, ExecutionMode.SINGLE, reason)
