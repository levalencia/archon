"""Structured logging configuration with correlation ID support.

Every log entry includes:
- timestamp (ISO 8601)
- level
- event (what happened)
- correlation_id (links all logs for a single request)
- Any additional context fields

See: https://github.com/levalencia/production-ai-agents/articles/day-01-anatomy-of-production-agent/
Concept: Layer 6 - Observability
"""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

import structlog

# ContextVar for request-scoped correlation ID
correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="")
_VALUE_PATTERN = re.compile(
    r"(?i)(bearer\s+)[a-z0-9._~+/=-]+|((?:api[-_]?key|token|password)\s*[:=]\s*)[^\s,;}]+"
)
_SENSITIVE_KEYS = re.compile(r"(?i)(authorization|api[-_]?key|token|secret|password|cookie)")


def redact_sensitive(value: str) -> str:
    """Redact common credentials embedded in free-form values."""
    return _VALUE_PATTERN.sub(lambda match: f"{match.group(1) or match.group(2)}[REDACTED]", value)


def redact_event(logger: structlog.types.WrappedLogger, method_name: str, event_dict: dict) -> dict:
    """Recursively redact credentials before rendering or log-stream capture."""
    del logger, method_name

    def clean(value, key=""):
        if _SENSITIVE_KEYS.search(str(key)):
            return "[REDACTED]"
        if isinstance(value, dict):
            return {k: clean(v, k) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [clean(item) for item in value]
        return redact_sensitive(value) if isinstance(value, str) else value

    return clean(event_dict)


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
    """Configure structlog for the application.

    Args:
        json_format: True for production (JSON lines), False for dev (colored console).
        log_level: Minimum log level.
    """
    processors: list = [
        structlog.contextvars.merge_contextvars,
        add_correlation_id,
        redact_event,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
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
