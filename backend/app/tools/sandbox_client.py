"""Fail-closed Unix-domain socket client for the isolated sandbox runner."""

from __future__ import annotations

import asyncio
import json
import math
import secrets
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.tools.sandbox import ExecutionKind, SandboxResult

_MAX_FRAME_BYTES = 1_100_000


@dataclass(frozen=True, slots=True)
class SandboxClientConfig:
    socket_path: str
    timeout_seconds: float
    output_bytes: int
    input_bytes: int = 1_048_576


class SandboxRunnerClient:
    """Execute only the versioned runner contract; never falls back to host execution."""

    def __init__(self, config: SandboxClientConfig) -> None:
        if not Path(config.socket_path).is_absolute():
            raise ValueError("Sandbox runner socket path must be absolute")
        if (
            isinstance(config.timeout_seconds, bool)
            or not isinstance(config.timeout_seconds, (int, float))
            or not math.isfinite(config.timeout_seconds)
            or not 0.1 <= config.timeout_seconds <= 120
            or type(config.output_bytes) is not int
            or not 1024 <= config.output_bytes <= 1_048_576
            or type(config.input_bytes) is not int
            or not 1024 <= config.input_bytes <= 1_048_576
        ):
            raise ValueError("Sandbox runner limits are invalid")
        self.config = config

    async def preflight(self) -> None:
        response = await self._request({"version": 1, "operation": "health"}, timeout=2.0)
        if response != {"version": 1, "status": "ok"}:
            raise RuntimeError("Sandbox runner health contract failed")

    async def execute(
        self, content: str, *, kind: ExecutionKind, timeout: float | None = None
    ) -> SandboxResult:
        if kind not in ("python", "shell"):
            raise ValueError("Unsupported execution kind")
        encoded = content.encode("utf-8")
        if len(encoded) > self.config.input_bytes:
            raise ValueError("Sandbox input exceeds configured limit")
        wall_timeout = self.config.timeout_seconds
        if timeout is not None:
            wall_timeout = min(max(timeout, 0.1), wall_timeout)
        request_id = secrets.token_hex(16)
        response = await self._request(
            {
                "version": 1,
                "operation": "execute",
                "request_id": request_id,
                "kind": kind,
                "content": content,
                "timeout_seconds": wall_timeout,
                "output_bytes": self.config.output_bytes,
            },
            timeout=wall_timeout + 2.0,
        )
        if response.get("request_id") != request_id:
            raise RuntimeError("Sandbox runner returned an invalid response")
        if response.get("status") == "error":
            code = response.get("error")
            if type(code) is not str or len(code) > 64:
                code = "invalid_response"
            raise RuntimeError(f"Sandbox runner rejected request: {code}")
        expected = {
            "version",
            "status",
            "request_id",
            "stdout",
            "stderr",
            "exit_code",
            "timed_out",
            "truncated",
            "isolation",
        }
        if set(response) != expected or response.get("status") != "ok":
            raise RuntimeError("Sandbox runner returned an invalid response")
        if (
            type(response["stdout"]) is not str
            or type(response["stderr"]) is not str
            or type(response["exit_code"]) is not int
            or type(response["timed_out"]) is not bool
            or type(response["truncated"]) is not bool
            or response["isolation"] != "runner-container"
            or len(response["stdout"].encode()) + len(response["stderr"].encode())
            > self.config.output_bytes
        ):
            raise RuntimeError("Sandbox runner returned an invalid response")
        return SandboxResult(
            response["stdout"],
            response["stderr"],
            response["exit_code"],
            response["timed_out"],
            response["truncated"],
            response["isolation"],
        )

    async def _request(self, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        writer: asyncio.StreamWriter | None = None
        try:
            async with asyncio.timeout(timeout):
                reader, writer = await asyncio.open_unix_connection(
                    self.config.socket_path, limit=_MAX_FRAME_BYTES + 1
                )
                frame = (
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
                )
                if len(frame) > _MAX_FRAME_BYTES:
                    raise ValueError("Sandbox request exceeds protocol limit")
                writer.write(frame)
                await writer.drain()
                line = await reader.readline()
                if not line or len(line) > _MAX_FRAME_BYTES or not line.endswith(b"\n"):
                    raise RuntimeError("Sandbox runner returned an invalid response")
                decoded = json.loads(line)
                if type(decoded) is not dict:
                    raise RuntimeError("Sandbox runner returned an invalid response")
                return decoded
        except (FileNotFoundError, ConnectionError, json.JSONDecodeError, TimeoutError) as exc:
            raise RuntimeError("Sandbox runner is unavailable") from exc
        finally:
            if writer is not None:
                writer.close()
                with suppress(ConnectionError, BrokenPipeError):
                    await writer.wait_closed()
