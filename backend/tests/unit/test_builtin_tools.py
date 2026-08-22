"""Tests for built-in tools."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.tools.builtin import (
    calculator_tool,
    datetime_tool,
    list_directory_tool,
    read_file_tool,
    register_builtin_tools,
    write_file_tool,
)
from app.tools.registry import SecureToolRegistry
from app.tools.web_search import web_search_tool


class TestCalculatorTool:
    """Calculator tool tests."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_basic_addition(self) -> None:
        result = await calculator_tool("2 + 3")
        assert result["result"] == 5.0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_complex_expression(self) -> None:
        result = await calculator_tool("(10 + 5) * 2")
        assert result["result"] == 30.0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_pi(self) -> None:
        result = await calculator_tool("pi")
        assert abs(result["result"] - 3.14159) < 0.001

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_sqrt(self) -> None:
        result = await calculator_tool("sqrt(16)")
        assert result["result"] == 4.0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_invalid_expression(self) -> None:
        result = await calculator_tool("import os")
        assert "error" in result


class TestDatetimeTool:
    """Datetime tool tests."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_now(self) -> None:
        result = await datetime_tool("now")
        assert "datetime" in result
        assert "date" in result
        assert "time" in result
        assert result["timezone"] == "UTC"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_date_only(self) -> None:
        result = await datetime_tool("date")
        assert "date" in result
        assert "-" in result["date"]  # YYYY-MM-DD format

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_timestamp(self) -> None:
        result = await datetime_tool("timestamp")
        assert "timestamp" in result
        assert isinstance(result["timestamp"], float)


class TestWebSearchTool:
    """Web search tool tests (mock results)."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_returns_results(self) -> None:
        result = await web_search_tool("Python programming")
        assert result["total"] >= 1
        assert len(result["results"]) >= 1

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_result_structure(self) -> None:
        result = await web_search_tool("AI agents")
        for r in result["results"]:
            assert "title" in r
            assert "url" in r
            assert "snippet" in r

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_max_results(self) -> None:
        result = await web_search_tool("test", max_results=2)
        assert len(result["results"]) <= 2  # Real search may return fewer


class TestFileTool:
    """File read/write/list tool tests."""

    @pytest.fixture
    def workspace(self) -> Path:
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            (ws / "test.txt").write_text("Hello World")
            (ws / "data.json").write_text('{"key": "value"}')
            (ws / "subdir").mkdir()
            yield ws

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_read_file(self, workspace: Path) -> None:
        result = await read_file_tool(str(workspace / "test.txt"))
        assert result["content"] == "Hello World"
        assert result["size"] == 11

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_read_nonexistent(self) -> None:
        result = await read_file_tool("/nonexistent/file.txt")
        assert "error" in result

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_directory(self, workspace: Path) -> None:
        result = await list_directory_tool(str(workspace))
        assert result["count"] == 3
        names = [i["name"] for i in result["items"]]
        assert "test.txt" in names
        assert "subdir" in names

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_write_file(self, workspace: Path) -> None:
        path = str(workspace / "new.txt")
        result = await write_file_tool(path, "New content")
        assert result["status"] == "written"
        assert Path(path).read_text() == "New content"


class TestRegisterBuiltinTools:
    """Built-in tool registration."""

    @pytest.mark.unit
    def test_registers_all_tools(self) -> None:
        registry = SecureToolRegistry()
        register_builtin_tools(registry)

        tools = registry.list_tools()
        names = [t["name"] for t in tools]
        assert "calculator" in names
        assert "datetime" in names
        assert "web_search" in names
        assert "read_file" in names
        assert "list_directory" in names
        assert "write_file" in names
        assert len(names) == 6
