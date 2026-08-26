"""Pure default policy rules for currently classified live tools."""

from __future__ import annotations

from app.security.policy import (
    PolicyAction,
    PolicyRule,
    ResourceKind,
    ResourcePattern,
    RiskClass,
    RulePolicyEngine,
)


def default_policy_rules() -> tuple[PolicyRule, ...]:
    """Return explicit conservative rules; unmatched requests never receive a global permit."""

    all_risks = frozenset(RiskClass)
    return (
        # Broad ASK comes first so the equally-specific READ rule below wins for pure reads.
        # Combined risks and all non-read effects still require authorization.
        PolicyRule(
            "side_effects_require_approval",
            PolicyAction.ASK,
            risk_classes=all_risks,
            description="non-read and combined-risk operations require approval",
        ),
        PolicyRule(
            "reads_allowed",
            PolicyAction.ALLOW,
            risk_classes=frozenset({RiskClass.READ}),
            description="pure read operations are allowed",
        ),
        PolicyRule(
            "web_search_network_allowed",
            PolicyAction.ALLOW,
            resources=(ResourcePattern(ResourceKind.TOOL, "web_search"),),
            risk_classes=frozenset({RiskClass.NETWORK}),
            description="the exact web_search tool may access the network",
        ),
    )


def default_policy_engine() -> RulePolicyEngine:
    """Build a new immutable engine with a deny fallback and no shared mutable state."""

    return RulePolicyEngine(default_policy_rules(), default_action=PolicyAction.DENY)


def create_default_policy_engine() -> RulePolicyEngine:
    """Compatibility-friendly explicit factory name."""

    return default_policy_engine()


class DefaultPolicyEngine(RulePolicyEngine):
    """Convenient constructible form of the same immutable default rule set."""

    def __init__(self) -> None:
        super().__init__(default_policy_rules(), default_action=PolicyAction.DENY)
