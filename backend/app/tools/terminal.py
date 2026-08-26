"""Terminal tool validation and isolated-executor adapter."""

from __future__ import annotations

import re

import structlog

from app.tools.sandbox import SandboxExecutor

logger = structlog.get_logger()

# Defense in depth only. Docker is the security boundary.
BLOCKED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\brm\s+(-\w*r\w*f|-\w*f\w*r)\b"),
    re.compile(r"\brm\s+-rf\b"),
    re.compile(r"\bsudo\b"),
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bdd\s+if="),
    re.compile(r"\b:()\s*\{"),
    re.compile(r"\bchmod\s+777\b"),
    re.compile(r"\bchown\b"),
    re.compile(r"\bshutdown\b"),
    re.compile(r"\breboot\b"),
    re.compile(r"\binit\s+0\b"),
    re.compile(r"\bkill\s+-9\s+-1\b"),
    re.compile(r">\s*/dev/sd[a-z]"),
    re.compile(r"\bcurl\b.*\|\s*(ba)?sh"),
    re.compile(r"\bwget\b.*\|\s*(ba)?sh"),
]


def is_command_blocked(command: str) -> str | None:
    for pattern in BLOCKED_PATTERNS:
        if pattern.search(command):
            return f"Blocked: command matches dangerous pattern '{pattern.pattern}'"
    return None


async def terminal_tool(
    command: str, timeout: int = 30, *, executor: SandboxExecutor | None = None
) -> dict[str, object]:
    """Legacy adapter; never executes unless an isolated executor was injected."""
    if executor is None:
        raise RuntimeError("Terminal execution is disabled: no isolated executor configured")
    blocked = is_command_blocked(command)
    if blocked:
        logger.warning("terminal_command_blocked", reason="dangerous_pattern")
        return {"stdout": "", "stderr": blocked, "exit_code": 1, "timed_out": False}
    return (
        await executor.execute(command, kind="shell", timeout=max(1, min(timeout, 120)))
    ).to_dict()
