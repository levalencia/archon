"""Tests for code_execute tool wiring in the tool registry."""

from __future__ import annotations

import pytest

from app.routes.chat import _create_tool_registry


def test_code_execute_registered():
    """code_execute tool is present in the registry."""
    registry = _create_tool_registry()
    tool = registry.get_tool("code_execute")
    assert tool is not None
    assert tool.name == "code_execute"
    assert "Python code" in tool.description
    assert "stdout" in tool.description


def test_code_execute_schema_has_code_property():
    """code_execute tool schema requires 'code' input."""
    registry = _create_tool_registry()
    tool = registry.get_tool("code_execute")
    assert tool is not None
    assert "code" in tool.input_schema.get("required", [])
    props = tool.input_schema.get("properties", {})
    assert "code" in props
    assert props["code"]["type"] == "string"


@pytest.mark.asyncio
async def test_code_execute_runs_simple_code():
    """code_execute handler runs Python code and returns expected keys."""
    registry = _create_tool_registry()
    result = await registry.execute("code_execute", {"code": "print('hello')"})
    assert "stdout" in result
    assert "exit_code" in result
    assert result["stdout"].strip() == "hello"
    assert result["exit_code"] == 0


def test_code_execute_appears_in_definitions():
    """code_execute appears in provider-neutral tool definitions."""
    registry = _create_tool_registry()
    defs = registry.definitions()
    names = [d.name for d in defs]
    assert "code_execute" in names
