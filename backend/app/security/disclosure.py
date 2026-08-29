"""Fail-closed disclosure-time PII and secret removal."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.security.pii_detector import PIIDetector

_SECRETS = (
    (
        "private_key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?"
            r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
        ),
    ),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}")),
    ("api_key", re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*[^\s,;]{8,}")),
    ("provider_key", re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16})\b")),
)


_SENSITIVE_OBJECT_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "bearer_token",
        "client_secret",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "token",
    }
)


def _normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


@dataclass(frozen=True, slots=True)
class DisclosureResult:
    value: Any
    redaction_count: int
    redaction_types: tuple[str, ...]


class DisclosureScanError(ValueError):
    pass


class DisclosureScanner:
    """Scan every disclosed string; detected values never enter metadata."""

    def __init__(self, detector: PIIDetector | None = None) -> None:
        self._pii = detector or PIIDetector(use_spacy=False)

    def scan(self, value: Any) -> DisclosureResult:
        counts: Counter[str] = Counter()
        ancestors: set[int] = set()
        nodes = 0

        def visit(item: Any, depth: int = 0) -> Any:
            nonlocal nodes
            nodes += 1
            if depth > 32 or nodes > 100_000:
                raise DisclosureScanError("disclosure payload exceeds structural limits")
            if isinstance(item, str):
                entities = self._pii.non_overlapping(self._pii.detect(item))
                for entity in entities:
                    counts[f"pii:{entity.entity_type}"] += 1
                text = self._pii.redact_entities(item, entities)
                for kind, pattern in _SECRETS:
                    text, found = pattern.subn(f"[REDACTED_{kind.upper()}]", text)
                    counts[f"secret:{kind}"] += found
                return text
            if isinstance(item, Mapping):
                identity = id(item)
                if identity in ancestors:
                    raise DisclosureScanError("disclosure payload contains a cycle")
                ancestors.add(identity)
                try:
                    result: dict[str, Any] = {}
                    for key, child in item.items():
                        if not isinstance(key, str):
                            raise DisclosureScanError("disclosure object keys must be strings")
                        safe_key = visit(key, depth + 1)
                        if safe_key in result:
                            raise DisclosureScanError("redaction produced duplicate object keys")
                        normalized_key = _normalized_key(key)
                        if normalized_key in _SENSITIVE_OBJECT_KEYS:
                            if child == "[REDACTED_STRUCTURED_SECRET]":
                                result[safe_key] = child
                            else:
                                counts[f"secret:structured:{normalized_key}"] += 1
                                result[safe_key] = "[REDACTED_STRUCTURED_SECRET]"
                        else:
                            result[safe_key] = visit(child, depth + 1)
                    return result
                finally:
                    ancestors.remove(identity)
            if isinstance(item, Sequence) and not isinstance(item, (bytes, bytearray)):
                identity = id(item)
                if identity in ancestors:
                    raise DisclosureScanError("disclosure payload contains a cycle")
                ancestors.add(identity)
                try:
                    return [visit(child, depth + 1) for child in item]
                finally:
                    ancestors.remove(identity)
            if item is None or type(item) in (bool, int):
                return item
            if type(item) is float:
                if not math.isfinite(item):
                    raise DisclosureScanError("disclosure payload contains a non-finite number")
                return item
            raise DisclosureScanError("disclosure payload contains an unsupported value")

        scanned = visit(value)
        return DisclosureResult(scanned, sum(counts.values()), tuple(sorted(counts)))
