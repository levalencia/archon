"""Compliance framework: input/output policy checks for LLM responses.

Course reference: Day 12 – Compliance Framework
Enforces content policies (max length, forbidden topics, required disclaimers).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class CompliancePolicy:
    """A set of content-compliance rules."""

    max_response_length: int = 10_000
    forbidden_topics: list[str] = field(default_factory=list)
    required_disclaimers: dict[str, str] = field(default_factory=dict)
    content_categories: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "max_response_length": self.max_response_length,
            "forbidden_topics": self.forbidden_topics,
            "required_disclaimers": self.required_disclaimers,
            "content_categories": self.content_categories,
        }


def _default_policy() -> CompliancePolicy:
    return CompliancePolicy(
        max_response_length=10_000,
        forbidden_topics=["bomb-making", "hacking tutorial", "illegal drugs synthesis"],
        required_disclaimers={
            "medical": (
                "This is not medical advice. Please consult a qualified healthcare professional."
            ),
            "legal": "This is not legal advice. Please consult a qualified attorney.",
            "financial": (
                "This is not financial advice. Please consult a qualified financial advisor."
            ),
        },
        content_categories=["medical", "legal", "financial"],
    )


_TOPIC_PATTERNS: dict[str, re.Pattern] = {}


def _get_topic_pattern(topic: str) -> re.Pattern:
    if topic not in _TOPIC_PATTERNS:
        _TOPIC_PATTERNS[topic] = re.compile(re.escape(topic), re.IGNORECASE)
    return _TOPIC_PATTERNS[topic]


_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "medical": [
        "diagnosis",
        "treatment",
        "medication",
        "symptom",
        "prescription",
        "dosage",
        "medical advice",
    ],
    "legal": ["legal advice", "lawsuit", "attorney", "court ruling", "legal opinion", "liability"],
    "financial": [
        "investment advice",
        "stock pick",
        "financial advice",
        "portfolio recommendation",
    ],
}


class ComplianceChecker:
    """Stateless checker that applies a :class:`CompliancePolicy` to text."""

    def __init__(self, policy: CompliancePolicy | None = None) -> None:
        self.policy = policy or _default_policy()

    # -- public API -----------------------------------------------------------

    def check_input(self, text: str) -> dict:
        """Check user input against the policy.

        Returns ``{compliant: bool, violations: [str]}``.
        """
        violations: list[str] = []

        for topic in self.policy.forbidden_topics:
            if _get_topic_pattern(topic).search(text):
                violations.append(f"Forbidden topic detected: {topic}")

        return {"compliant": len(violations) == 0, "violations": violations}

    def check_output(self, text: str) -> dict:
        """Check LLM output against the policy.

        Returns ``{compliant: bool, violations: [str], remediated_text: str}``.
        """
        violations: list[str] = []
        remediated = text

        # Length check
        if len(text) > self.policy.max_response_length:
            violations.append(
                f"Response exceeds max length ({len(text)} > {self.policy.max_response_length})"
            )
            remediated = text[: self.policy.max_response_length]

        # Forbidden topics in output
        for topic in self.policy.forbidden_topics:
            if _get_topic_pattern(topic).search(text):
                violations.append(f"Forbidden topic in output: {topic}")

        # Required disclaimers for detected categories
        for category in self.policy.content_categories:
            keywords = _CATEGORY_KEYWORDS.get(category, [])
            if any(kw.lower() in text.lower() for kw in keywords):
                disclaimer = self.policy.required_disclaimers.get(category, "")
                if disclaimer and disclaimer not in remediated:
                    violations.append(f"Missing required {category} disclaimer")
                    remediated = remediated.rstrip() + f"\n\n⚠️ {disclaimer}"

        return {
            "compliant": len(violations) == 0,
            "violations": violations,
            "remediated_text": remediated,
        }

    def get_policies(self) -> dict:
        """Return the active policy as a JSON-serialisable dict."""
        return self.policy.to_dict()


class ComplianceViolationError(ValueError):
    """A mandatory compliance boundary rejected unsafe content."""

    def __init__(self, direction: str, violations: list[str]) -> None:
        super().__init__(f"{direction} rejected by compliance policy")
        self.direction = direction
        self.violation_codes = tuple(
            "forbidden_topic" if item.lower().startswith("forbidden") else "policy_violation"
            for item in violations
        )


class MandatoryComplianceService:
    """Single fail-closed boundary used by persistence and effect paths."""

    def __init__(self, checker: ComplianceChecker | None = None) -> None:
        self._checker = checker or ComplianceChecker()

    def enforce_input(self, text: str) -> None:
        result = self._checker.check_input(text)
        if not result["compliant"]:
            raise ComplianceViolationError("input", result["violations"])

    def enforce_output(self, text: str) -> str:
        result = self._checker.check_output(text)
        forbidden = [item for item in result["violations"] if item.startswith("Forbidden topic")]
        if forbidden:
            return "[Response withheld by compliance policy]"
        return str(result["remediated_text"])

    def enforce_dangerous_tool(self, tool_name: str, arguments: object) -> None:
        import json

        # Validation is deliberately content-only: policy and approval remain authoritative
        # for tool identity, scope, and effect authorization.
        serialized = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)
        self.enforce_input(serialized)

    def enforce_payload(self, value: object) -> object:
        """Remediate every disclosed string while preserving JSON-compatible structure."""
        if isinstance(value, str):
            return self.enforce_output(value)
        if isinstance(value, dict):
            return {key: self.enforce_payload(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.enforce_payload(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.enforce_payload(item) for item in value)
        return value


# Module-level default instances for easy import
default_checker = ComplianceChecker()
default_compliance = MandatoryComplianceService(default_checker)
