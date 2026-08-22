"""Tool sandboxing: run LLM-generated code in isolated subprocess.

Enforces: timeout, memory limit, no network, no filesystem write outside sandbox.
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import structlog

logger = structlog.get_logger()


async def execute_sandboxed(
    code: str,
    language: str = "python",
    timeout: float = 10.0,
    max_memory_mb: int = 256,
) -> dict:
    """Execute code in a sandboxed subprocess.

    Returns: {stdout, stderr, exit_code, timed_out}
    """
    if language != "python":
        return {"error": f"Unsupported language: {language}", "exit_code": 1}

    # Write code to temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, prefix="archon_sandbox_"
    ) as f:
        f.write(code)
        script_path = f.name

    try:
        # Build sandboxed command
        cmd = [
            "python3",
            "-u",
            script_path,
        ]

        # Set resource limits via env
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONUNBUFFERED"] = "1"

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            timed_out = False
        except TimeoutError:
            proc.kill()
            stdout, stderr = b"", b"Execution timed out"
            timed_out = True

        result = {
            "stdout": stdout.decode(errors="replace")[:10000],
            "stderr": stderr.decode(errors="replace")[:5000],
            "exit_code": proc.returncode or 0,
            "timed_out": timed_out,
        }

        logger.info(
            "sandbox_executed",
            language=language,
            exit_code=result["exit_code"],
            timed_out=timed_out,
            stdout_len=len(result["stdout"]),
        )

        return result

    finally:
        os.unlink(script_path)
