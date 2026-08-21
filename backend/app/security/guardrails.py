"""Input/output guardrails for agent safety.

Input guardrails: block prompt injection, excessive length, suspicious patterns.
Output guardrails: block harmful content, check for PII leakage, validate format.

See: https://github.com/levalencia/production-ai-agents/
Concept: Layer 5 - Guardrails (input/output validation)
"""

from __future__ import annotations

import re

import structlog

from app.security.pii_detector import PIIDetector

logger = structlog.get_logger()

# Common prompt injection patterns
INJECTION_PATTERNS: list[tuple[str, str]] = [
    (
        r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|rules?)",
        "ignore_instructions",
    ),
    (r"you\s+are\s+now\s+(a|an|the)\s+", "role_override"),
    (r"system\s*:\s*", "system_prefix_injection"),
    (r"<\|?(system|im_start|endoftext)\|?>", "special_token_injection"),
    (r"forget\s+(everything|all|your)\s+(you|instructions?|rules?)", "memory_wipe"),
    (r"pretend\s+(you\s+are|to\s+be|you're)", "pretend_attack"),
    (r"act\s+as\s+(if|though)?\s*(you\s+are|a|an)", "act_as_attack"),
    (r"do\s+not\s+follow\s+(any|your|the)\s+(rules?|instructions?)", "rule_override"),
]


class GuardrailResult:
    """Result of a guardrail check."""

    def __init__(
        self,
        allowed: bool,
        reason: str = "",
        triggered_rules: list[str] | None = None,
        redacted_text: str | None = None,
    ) -> None:
        self.allowed = allowed
        self.reason = reason
        self.triggered_rules = triggered_rules or []
        self.redacted_text = redacted_text

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "triggered_rules": self.triggered_rules,
            "redacted_text": self.redacted_text,
        }


class InputGuardrail:
    """Validates user input before it reaches the agent."""

    def __init__(
        self,
        max_length: int = 10000,
        check_injection: bool = True,
        custom_patterns: list[tuple[str, str]] | None = None,
    ) -> None:
        self._max_length = max_length
        self._check_injection = check_injection
        patterns = INJECTION_PATTERNS + (custom_patterns or [])
        self._compiled = [(re.compile(p, re.IGNORECASE), name) for p, name in patterns]

    async def check_input(self, text: str) -> dict:
        """Validate input text. Returns {allowed, reason, triggered_rules}."""
        triggered: list[str] = []

        # Length check
        if len(text) > self._max_length:
            return GuardrailResult(
                allowed=False,
                reason=f"Input too long ({len(text)} > {self._max_length})",
                triggered_rules=["max_length"],
            ).to_dict()

        # Empty check
        if not text.strip():
            return GuardrailResult(
                allowed=False,
                reason="Empty input",
                triggered_rules=["empty_input"],
            ).to_dict()

        # Injection patterns
        if self._check_injection:
            for pattern, name in self._compiled:
                if pattern.search(text):
                    triggered.append(name)

        if triggered:
            logger.warning(
                "input_guardrail_triggered",
                rules=triggered,
                input_length=len(text),
            )
            return GuardrailResult(
                allowed=False,
                reason=f"Potential prompt injection detected: {', '.join(triggered)}",
                triggered_rules=triggered,
            ).to_dict()

        return GuardrailResult(allowed=True).to_dict()


class OutputGuardrail:
    """Validates agent output before it reaches the user."""

    def __init__(
        self,
        pii_detector: PIIDetector | None = None,
        auto_redact_pii: bool = True,
        max_length: int = 50000,
    ) -> None:
        self._pii_detector = pii_detector or PIIDetector()
        self._auto_redact = auto_redact_pii
        self._max_length = max_length

    async def check_output(self, text: str) -> dict:
        """Validate output text. Returns {allowed, reason, redacted}."""
        triggered: list[str] = []

        # Length check
        if len(text) > self._max_length:
            return GuardrailResult(
                allowed=False,
                reason=f"Output too long ({len(text)} > {self._max_length})",
                triggered_rules=["max_length"],
            ).to_dict()

        # PII check
        entities = self._pii_detector.detect(text)
        redacted_text = text

        if entities:
            triggered.append("pii_detected")
            high_risk = [e for e in entities if e.risk_level == "high"]

            if high_risk:
                triggered.append("high_risk_pii")

            if self._auto_redact:
                redacted_text = self._pii_detector.redact(text)
                logger.warning(
                    "output_guardrail_pii_redacted",
                    pii_count=len(entities),
                    pii_types=[e.entity_type for e in entities],
                )

        if triggered and not self._auto_redact:
            return GuardrailResult(
                allowed=False,
                reason="PII detected in output",
                triggered_rules=triggered,
            ).to_dict()

        return GuardrailResult(
            allowed=True,
            triggered_rules=triggered,
            redacted_text=redacted_text if redacted_text != text else None,
        ).to_dict()
