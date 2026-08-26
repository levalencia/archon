"""Execution registry wiring tests: disabled means absent, enabled means injected."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.routes.chat import _create_tool_registry
from app.tools.sandbox import SandboxResult


@dataclass
class FakeExecutor:
    calls: list[tuple[str, str, float | None]]

    async def preflight(self) -> None:
        return None

    async def execute(
        self, content: str, *, kind: str, timeout: float | None = None
    ) -> SandboxResult:
        self.calls.append((content, kind, timeout))
        return SandboxResult("hello\n", "", 0, False, False)


def test_execution_tools_absent_without_executor() -> None:
    registry = _create_tool_registry()
    assert registry.get_tool("code_execute") is None
    assert registry.get_tool("terminal") is None
    assert "code_execute" not in {definition.name for definition in registry.definitions()}


@pytest.mark.asyncio
async def test_execution_tools_use_injected_executor() -> None:
    executor = FakeExecutor([])
    registry = _create_tool_registry(sandbox_executor=executor)
    assert registry.get_tool("code_execute") is not None
    assert registry.get_tool("terminal") is not None
    result = await registry.execute("code_execute", {"code": "print('hello')"})
    assert result["stdout"] == "hello\n"
    assert executor.calls == [("print('hello')", "python", None)]
