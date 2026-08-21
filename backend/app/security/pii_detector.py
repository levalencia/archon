"""PII detection using regex patterns.

Detects: email, phone, SSN, credit card, IP address, date of birth patterns.
Returns detected entities with type, value, position, and risk level.

See: https://github.com/levalencia/production-ai-agents/
Concept: Layer 5 - Guardrails (PII detection and redaction)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import structlog

logger = structlog.get_logger()


@dataclass
class PIIEntity:
    """A detected PII entity."""

    entity_type: str
    value: str
    start: int
    end: int
    risk_level: str = "medium"  # low, medium, high


# PII detection patterns
PII_PATTERNS: dict[str, tuple[str, str]] = {
    "email": (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "medium"),
    "phone_us": (r"\b(?:\+1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}\b", "medium"),
    "phone_intl": (r"\b\+\d{1,3}[-.\s]?\d{4,14}\b", "medium"),
    "ssn": (r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b", "high"),
    "credit_card": (r"\b(?:\d{4}[-\s]?){3}\d{4}\b", "high"),
    "ip_address": (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "low"),
    "date_of_birth": (
        r"\b(?:DOB|Date of Birth|born on)[:\s]*\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b",
        "high",
    ),
}

# Redaction placeholder
REDACTION_CHAR = "*"


class PIIDetector:
    """Regex-based PII detection and redaction.

    Satisfies the PIIDetector Protocol (from protocols.py).
    """

    def __init__(
        self,
        patterns: dict[str, tuple[str, str]] | None = None,
        redaction_char: str = REDACTION_CHAR,
    ) -> None:
        self._patterns = patterns or PII_PATTERNS
        self._redaction_char = redaction_char
        self._compiled = {
            name: re.compile(pattern, re.IGNORECASE)
            for name, (pattern, _) in self._patterns.items()
        }

    def detect(self, text: str) -> list[PIIEntity]:
        """Detect PII entities in text."""
        entities: list[PIIEntity] = []

        for entity_type, compiled in self._compiled.items():
            risk_level = self._patterns[entity_type][1]
            for match in compiled.finditer(text):
                entities.append(
                    PIIEntity(
                        entity_type=entity_type,
                        value=match.group(),
                        start=match.start(),
                        end=match.end(),
                        risk_level=risk_level,
                    )
                )

        # Sort by position
        entities.sort(key=lambda e: e.start)

        if entities:
            logger.info(
                "pii_detected",
                count=len(entities),
                types=[e.entity_type for e in entities],
                risk_levels=[e.risk_level for e in entities],
            )

        return entities

    def redact(self, text: str) -> str:
        """Detect and redact PII from text."""
        entities = self.detect(text)
        if not entities:
            return text

        # Redact from end to start to preserve positions
        result = text
        for entity in reversed(entities):
            replacement = f"[{entity.entity_type.upper()}]"
            result = result[: entity.start] + replacement + result[entity.end :]

        return result

    def assess_risk(self, text: str) -> str:
        """Assess overall PII risk level of text."""
        entities = self.detect(text)
        if not entities:
            return "none"

        risk_order = {"low": 1, "medium": 2, "high": 3}
        max_risk = max(risk_order.get(e.risk_level, 0) for e in entities)
        risk_map = {1: "low", 2: "medium", 3: "high"}
        return risk_map.get(max_risk, "unknown")
