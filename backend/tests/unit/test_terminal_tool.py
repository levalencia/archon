"""Terminal blocklist and no-host-fallback tests."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.tools.sandbox import SandboxResult
from app.tools.terminal import is_command_blocked, terminal_tool


@dataclass
class FakeExecutor:
    calls: list[tuple[str, str, float | None]]

    async def preflight(self) -> None:
        return None

    async def execute(
        self, content: str, *, kind: str, timeout: float | None = None
    ) -> SandboxResult:
        self.calls.append((content, kind, timeout))
        return SandboxResult("ok", "", 0, False, False)


@pytest.mark.parametrize("command", ["rm -rf /", "sudo id", "mkfs.ext4 /dev/sda", "reboot"])
def test_dangerous_commands_blocked(command: str) -> None:
    assert is_command_blocked(command) is not None


def test_safe_command_allowed() -> None:
    assert is_command_blocked("printf hello") is None


@pytest.mark.asyncio
async def test_terminal_has_no_host_fallback() -> None:
    with pytest.raises(RuntimeError, match="no isolated executor"):
        await terminal_tool("printf host")


@pytest.mark.asyncio
async def test_terminal_delegates_content_to_injected_executor() -> None:
    executor = FakeExecutor([])
    result = await terminal_tool("printf ok", timeout=999, executor=executor)
    assert result["stdout"] == "ok"
    assert executor.calls == [("printf ok", "shell", 120)]


@pytest.mark.asyncio
async def test_blocklist_runs_before_executor() -> None:
    executor = FakeExecutor([])
    result = await terminal_tool("sudo id", executor=executor)
    assert result["exit_code"] == 1
    assert executor.calls == []
