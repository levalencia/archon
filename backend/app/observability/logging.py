"""Structured logging configuration with correlation ID and redaction support."""

from __future__ import annotations

import re
import uuid
from collections import Counter
from collections.abc import Mapping
from contextvars import ContextVar
from hashlib import sha256
from typing import Any, cast

import structlog

from app.security.persistence_redactor import PersistenceRedactor
from app.security.pii_detector import PIIDetector

# ContextVar for request-scoped correlation ID
correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="")
_VALUE_PATTERN = re.compile(
    r"(?i)(bearer\s+)[a-z0-9._~+/=-]+|((?:api[-_]?key|token|password)\s*[:=]\s*)[^\s,;}]+"
)
_SENSITIVE_KEYS = re.compile(r"(?i)(authorization|api[-_]?key|token|secret|password|cookie)")
# Logging must remain deterministic and must not initialize spaCy, which logs while loading.
_LOG_REDACTOR = PersistenceRedactor(PIIDetector(use_spacy=False))


def redact_sensitive(value: str) -> str:
    """Redact common credentials embedded in free-form values."""
    return _VALUE_PATTERN.sub(lambda match: f"{match.group(1) or match.group(2)}[REDACTED]", value)


def safe_value_metadata(name: str, value: str) -> dict[str, int | str]:
    """Return useful, non-reversible metadata for a user-controlled value."""
    return {
        f"{name}_length": len(value),
        f"{name}_sha256": sha256(value.encode("utf-8")).hexdigest()[:12],
    }


def safe_exception_metadata(exc: BaseException, reason: str) -> dict[str, str]:
    """Describe an exception without persisting its potentially sensitive message."""
    return {"error_type": type(exc).__name__, "error_reason": reason}


def redact_event(
    logger: structlog.types.WrappedLogger, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Recursively redact PII and credentials before rendering or capture.

    String mapping keys are redacted too. If redaction collapses two keys, a safe
    ordinal suffix preserves both entries. Non-string values and key types are
    retained so logging-required fields keep their expected types.
    """
    del logger, method_name

    def clean_string(value: str) -> str:
        return _LOG_REDACTOR.redact_text(redact_sensitive(value)).text

    def clean(value: Any, key: object = "") -> Any:
        if isinstance(key, str) and _SENSITIVE_KEYS.search(key):
            return "[REDACTED]"
        if isinstance(value, Mapping):
            redacted: dict[Any, Any] = {}
            key_counts: Counter[Any] = Counter()
            for original_key, item in value.items():
                base_key = (
                    clean_string(original_key) if isinstance(original_key, str) else original_key
                )
                key_counts[base_key] += 1
                ordinal = key_counts[base_key]
                safe_key = base_key if ordinal == 1 else f"{base_key}__{ordinal}"
                while safe_key in redacted:
                    ordinal += 1
                    key_counts[base_key] = ordinal
                    safe_key = f"{base_key}__{ordinal}"
                redacted[safe_key] = clean(item, original_key)
            return redacted
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, tuple):
            return tuple(clean(item) for item in value)
        return clean_string(value) if isinstance(value, str) else value

    return cast(dict[str, Any], clean(event_dict))


def get_correlation_id() -> str:
    """Get the current correlation ID, or generate one."""
    cid = correlation_id_ctx.get()
    if not cid:
        cid = str(uuid.uuid4())
        correlation_id_ctx.set(cid)
    return cid


def set_correlation_id(cid: str) -> None:
    """Set the correlation ID for the current context."""
    correlation_id_ctx.set(cid)


def new_correlation_id() -> str:
    """Generate and set a new correlation ID."""
    cid = str(uuid.uuid4())
    correlation_id_ctx.set(cid)
    return cid


def add_correlation_id(
    logger: structlog.types.WrappedLogger,
    method_name: str,
    event_dict: dict,
) -> dict:
    """Structlog processor that injects correlation_id into every log entry."""
    cid = correlation_id_ctx.get()
    if cid:
        event_dict["correlation_id"] = cid
    return event_dict


def setup_logging(*, json_format: bool = True, log_level: str = "INFO") -> None:
    """Configure structlog for JSON production or console development output."""
    processors: list = [
        structlog.contextvars.merge_contextvars,
        add_correlation_id,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        # Keep this last before either renderer so preceding processors cannot add PII.
        redact_event,
    ]

    if json_format:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(__import__("logging"), log_level.upper(), 20)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
