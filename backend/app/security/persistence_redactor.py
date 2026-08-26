"""PII-safe boundary for data that is about to be persisted."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.security.pii_detector import PIIDetector


@dataclass(frozen=True, slots=True)
class RedactionResult:
    """Redacted value and non-sensitive detection metadata."""

    text: str
    count: int
    types: tuple[str, ...]


class PersistenceRedactor:
    """Redact text and structured values at persistence boundaries.

    Runtime/provider values are intentionally untouched. Metadata contains only
    entity types and counts; detected values never leave the detector.
    """

    def __init__(self, detector: PIIDetector | None = None) -> None:
        self._detector = detector or PIIDetector()

    def redact_text(self, text: str) -> RedactionResult:
        entities = self._detector.detect(text)
        redacted = self._detector.redact_entities(text, entities)
        counts = Counter(entity.entity_type for entity in self._detector.non_overlapping(entities))
        types = tuple(sorted(counts))
        return RedactionResult(redacted, sum(counts.values()), types)

    def redact_value(self, value: Any) -> Any:
        """Recursively redact strings, including mapping keys.

        Redaction can collapse distinct keys. Preserve every entry with an ordinal
        suffix that contains no part of either original key.
        """
        if isinstance(value, str):
            return self.redact_text(value).text
        if isinstance(value, Mapping):
            redacted: dict[str, Any] = {}
            key_counts: Counter[str] = Counter()
            for key, item in value.items():
                base_key = self.redact_text(str(key)).text
                key_counts[base_key] += 1
                ordinal = key_counts[base_key]
                safe_key = base_key if ordinal == 1 else f"{base_key}__{ordinal}"
                while safe_key in redacted:
                    ordinal += 1
                    key_counts[base_key] = ordinal
                    safe_key = f"{base_key}__{ordinal}"
                redacted[safe_key] = self.redact_value(item)
            return redacted
        if isinstance(value, tuple):
            return tuple(self.redact_value(item) for item in value)
        if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
            return [self.redact_value(item) for item in value]
        return value
