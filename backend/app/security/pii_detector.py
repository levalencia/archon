"""PII detection with optional spaCy NER support.

Uses regex patterns always + spaCy NER when installed for names/locations.
Plan item #24: regex + spaCy NER + contextual analysis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import structlog

logger = structlog.get_logger()


@dataclass
class PIIEntity:
    entity_type: str
    value: str
    start: int
    end: int
    risk_level: str = "medium"
    source: str = "regex"


# Regex patterns (always available)
PII_PATTERNS = {
    "email": (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "medium"),
    "phone": (re.compile(r"\b(?:\+?1[-.]?)?\(?\d{3}\)?[-.]?\d{3}[-.]?\d{4}\b"), "medium"),
    "ssn": (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "high"),
    "credit_card": (re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"), "high"),
    "ip_address": (re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"), "low"),
    "date_of_birth": (
        re.compile(r"\b(?:0[1-9]|1[0-2])/(?:0[1-9]|[12]\d|3[01])/(?:19|20)\d{2}\b"),
        "medium",
    ),
}

# Try to load spaCy for NER
_nlp = None
_spacy_available = False


def _init_spacy() -> bool:
    """Initialize spaCy NER model if available."""
    global _nlp, _spacy_available
    if _nlp is not None:
        return _spacy_available
    try:
        import spacy

        _nlp = spacy.load("en_core_web_sm")
        _spacy_available = True
        logger.info("spacy_ner_loaded", model="en_core_web_sm")
    except (ImportError, OSError):
        _nlp = None
        _spacy_available = False
        logger.info("spacy_not_available", fallback="regex-only")
    return _spacy_available


class PIIDetector:
    """Detect PII using regex + optional spaCy NER."""

    def __init__(self) -> None:
        self._compiled = PII_PATTERNS
        self._use_spacy = _init_spacy()

    def detect(self, text: str) -> list[PIIEntity]:
        """Detect all PII entities in text."""
        entities = []

        # Regex detection (always)
        for pii_type, (pattern, risk) in self._compiled.items():
            for match in pattern.finditer(text):
                entities.append(
                    PIIEntity(
                        entity_type=pii_type,
                        value=match.group(),
                        start=match.start(),
                        end=match.end(),
                        risk_level=risk,
                        source="regex",
                    )
                )

        # spaCy NER detection (when available)
        if self._use_spacy and _nlp is not None:
            doc = _nlp(text)
            for ent in doc.ents:
                if ent.label_ == "PERSON":
                    entities.append(
                        PIIEntity(
                            entity_type="person_name",
                            value=ent.text,
                            start=ent.start_char,
                            end=ent.end_char,
                            risk_level="medium",
                            source="spacy_ner",
                        )
                    )
                elif ent.label_ == "GPE":
                    entities.append(
                        PIIEntity(
                            entity_type="location",
                            value=ent.text,
                            start=ent.start_char,
                            end=ent.end_char,
                            risk_level="low",
                            source="spacy_ner",
                        )
                    )
                elif ent.label_ in ("ORG",):
                    entities.append(
                        PIIEntity(
                            entity_type="organization",
                            value=ent.text,
                            start=ent.start_char,
                            end=ent.end_char,
                            risk_level="low",
                            source="spacy_ner",
                        )
                    )

        return entities

    def redact(self, text: str) -> str:
        """Redact all PII from text."""
        entities = self.detect(text)
        entities.sort(key=lambda e: e.start, reverse=True)
        result = text
        for entity in entities:
            tag = f"[{entity.entity_type.upper()}]"
            result = result[: entity.start] + tag + result[entity.end :]
        return result

    def assess_risk(self, text: str) -> str:
        """Assess overall PII risk level."""
        entities = self.detect(text)
        if not entities:
            return "none"
        if any(e.risk_level == "high" for e in entities):
            return "high"
        if any(e.risk_level == "medium" for e in entities):
            return "medium"
        return "low"
