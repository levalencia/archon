"""Terminal/shell tool: execute shell commands safely with a blocklist.

Uses subprocess with timeout, captures stdout+stderr.
Dangerous commands (rm -rf, sudo, etc.) are blocked.
"""

from __future__ import annotations

import asyncio
import os
import re

import structlog

from app.observability.logging import safe_exception_metadata, safe_value_metadata

logger = structlog.get_logger()

# Patterns that are blocked for safety
BLOCKED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\brm\s+(-\w*r\w*f|-\w*f\w*r)\b"),  # rm -rf / rm -fr
    re.compile(r"\brm\s+-rf\b"),
    re.compile(r"\bsudo\b"),
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bdd\s+if="),
    re.compile(r"\b:()\s*\{"),  # fork bomb
    re.compile(r"\bchmod\s+777\b"),
    re.compile(r"\bchown\b"),
    re.compile(r"\bshutdown\b"),
    re.compile(r"\breboot\b"),
    re.compile(r"\binit\s+0\b"),
    re.compile(r"\bkill\s+-9\s+-1\b"),
    re.compile(r">\s*/dev/sd[a-z]"),
    re.compile(r"\bcurl\b.*\|\s*(ba)?sh"),  # curl | sh
    re.compile(r"\bwget\b.*\|\s*(ba)?sh"),
]


def is_command_blocked(command: str) -> str | None:
    """Return a reason string if the command is blocked, else None."""
    for pattern in BLOCKED_PATTERNS:
        if pattern.search(command):
            return f"Blocked: command matches dangerous pattern '{pattern.pattern}'"
    return None


async def terminal_tool(command: str, timeout: int = 30) -> dict:
    """Execute a shell command safely. Returns stdout, stderr, exit_code.

    Args:
        command: The shell command to execute.
        timeout: Maximum seconds to wait (default 30, max 120).

    Returns:
        dict with stdout, stderr, exit_code, timed_out keys.
    """
    # Validate timeout
    timeout = max(1, min(timeout, 120))

    # Check blocklist
    blocked = is_command_blocked(command)
    if blocked:
        logger.warning(
            "terminal_command_blocked",
            **safe_value_metadata("command", command),
            reason="dangerous_pattern",
        )
        return {"stdout": "", "stderr": blocked, "exit_code": 1, "timed_out": False}

    env = os.environ.copy()
    env["LC_ALL"] = "C"

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            timed_out = False
        except TimeoutError:
            proc.kill()
            stdout_bytes, stderr_bytes = b"", b"Command timed out"
            timed_out = True

        result = {
            "stdout": stdout_bytes.decode(errors="replace")[:10000],
            "stderr": stderr_bytes.decode(errors="replace")[:5000],
            "exit_code": proc.returncode or 0,
            "timed_out": timed_out,
        }

        logger.info(
            "terminal_executed",
            **safe_value_metadata("command", command),
            exit_code=result["exit_code"],
            timed_out=timed_out,
            stdout_len=len(result["stdout"]),
        )
        return result

    except Exception as exc:
        logger.error(
            "terminal_error",
            **safe_value_metadata("command", command),
            **safe_exception_metadata(exc, "execution_failed"),
        )
        return {
            "stdout": "",
            "stderr": f"Error executing command: {exc}",
            "exit_code": 1,
            "timed_out": False,
        }
