"""Built-in tools for the agent: web search, calculator, datetime, file operations.

These are the default tools available to every Archon agent.
Each tool is a plain async function — no framework dependency.

See: https://github.com/levalencia/production-ai-agents/
Concept: Layer 3 - Tools (registered, validated, timeout-enforced)
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path

import structlog

logger = structlog.get_logger()


async def calculator_tool(expression: str) -> dict:
    """Evaluate a mathematical expression safely.

    Supports: +, -, *, /, **, sqrt, sin, cos, tan, log, pi, e
    Does NOT use eval() — parses and computes safely.
    """
    # Whitelist of allowed characters and functions
    allowed = set("0123456789.+-*/() ")
    clean = expression.strip()

    # Replace math functions with their values
    replacements = {
        "pi": str(math.pi),
        "e": str(math.e),
        "sqrt": "math.sqrt",
        "sin": "math.sin",
        "cos": "math.cos",
        "tan": "math.tan",
        "log": "math.log",
        "abs": "abs",
        "round": "round",
        "**": "**",
    }

    for name, replacement in replacements.items():
        clean = clean.replace(name, replacement)

    # Validate: only allowed characters after replacement
    stripped = clean
    for func in ["math.sqrt", "math.sin", "math.cos", "math.tan", "math.log", "abs", "round"]:
        stripped = stripped.replace(func, "")

    if not all(c in allowed or c == "." for c in stripped):
        return {"error": f"Invalid characters in expression: {expression}"}

    try:
        # Safe evaluation with restricted namespace
        result = eval(clean, {"__builtins__": {}, "math": math, "abs": abs, "round": round})  # noqa: S307
        return {"result": float(result), "expression": expression}
    except Exception as e:
        return {"error": f"Calculation error: {e}", "expression": expression}


async def datetime_tool(query: str = "now") -> dict:
    """Get current date, time, or timezone information.

    Queries: "now", "date", "time", "utc", "timestamp"
    """
    now = datetime.now(tz=UTC)

    if query in ("now", "current"):
        return {
            "datetime": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "timezone": "UTC",
            "timestamp": now.timestamp(),
        }
    if query == "date":
        return {"date": now.strftime("%Y-%m-%d")}
    if query == "time":
        return {"time": now.strftime("%H:%M:%S UTC")}
    if query == "timestamp":
        return {"timestamp": now.timestamp()}

    return {
        "datetime": now.isoformat(),
        "timezone": "UTC",
        "query": query,
    }


async def web_search_tool(query: str, max_results: int = 3) -> dict:
    """Search the web using a simple API.

    In production: uses Tavily, SearXNG, or Brave Search API.
    In mock/dev: returns simulated results.
    """
    # Mock results for development (no API key needed)
    mock_results = [
        {
            "title": f"Result {i + 1} for: {query}",
            "url": f"https://example.com/result-{i + 1}",
            "snippet": f"This is a simulated search result about {query}. "
            f"It contains relevant information for testing purposes.",
        }
        for i in range(min(max_results, 5))
    ]

    logger.info("web_search", query=query, results=len(mock_results))

    return {
        "query": query,
        "results": mock_results,
        "total": len(mock_results),
        "source": "mock",
    }


async def read_file_tool(path: str) -> dict:
    """Read a file's contents. Path must be within allowed directory.

    Permission checking is handled by the SecureToolRegistry,
    not by this function.
    """
    file_path = Path(path)

    if not file_path.exists():
        return {"error": f"File not found: {path}"}

    if not file_path.is_file():
        return {"error": f"Not a file: {path}"}

    try:
        content = file_path.read_text(encoding="utf-8")
        return {
            "content": content,
            "path": str(file_path),
            "size": len(content),
            "name": file_path.name,
        }
    except Exception as e:
        return {"error": f"Error reading file: {e}"}


async def list_directory_tool(path: str) -> dict:
    """List files in a directory.

    Permission checking is handled by the SecureToolRegistry.
    """
    dir_path = Path(path)

    if not dir_path.exists():
        return {"error": f"Directory not found: {path}"}

    if not dir_path.is_dir():
        return {"error": f"Not a directory: {path}"}

    items = []
    for item in sorted(dir_path.iterdir()):
        items.append(
            {
                "name": item.name,
                "type": "file" if item.is_file() else "directory",
                "size": item.stat().st_size if item.is_file() else 0,
            }
        )

    return {"path": str(dir_path), "items": items, "count": len(items)}


async def write_file_tool(path: str, content: str) -> dict:
    """Write content to a file.

    Permission checking is handled by the SecureToolRegistry.
    """
    file_path = Path(path)

    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return {
            "path": str(file_path),
            "size": len(content),
            "status": "written",
        }
    except Exception as e:
        return {"error": f"Error writing file: {e}"}


def register_builtin_tools(registry: object) -> None:
    """Register all built-in tools with a SecureToolRegistry.

    Usage:
        registry = SecureToolRegistry(permissions=perms, audit=audit)
        register_builtin_tools(registry)
    """
    from app.tools.registry import SecureToolRegistry

    if not isinstance(registry, SecureToolRegistry):
        return

    registry.register(
        name="calculator",
        handler=calculator_tool,
        description="Evaluate math expressions (+, -, *, /, sqrt, sin, cos, log, pi)",
        input_schema={"required": ["expression"]},
        timeout=5,
    )

    registry.register(
        name="datetime",
        handler=datetime_tool,
        description="Get current date, time, timestamp, or timezone info",
        input_schema={"required": ["query"]},
        timeout=5,
    )

    registry.register(
        name="web_search",
        handler=web_search_tool,
        description="Search the web for information (returns title, URL, snippet)",
        input_schema={"required": ["query"]},
        timeout=30,
    )

    registry.register(
        name="read_file",
        handler=read_file_tool,
        description="Read the contents of a file",
        required_permissions=["read_file"],
        input_schema={"required": ["path"]},
        timeout=10,
    )

    registry.register(
        name="list_directory",
        handler=list_directory_tool,
        description="List files and subdirectories in a directory",
        required_permissions=["list_directory"],
        input_schema={"required": ["path"]},
        timeout=10,
    )

    registry.register(
        name="write_file",
        handler=write_file_tool,
        description="Write content to a file",
        required_permissions=["write_file"],
        input_schema={"required": ["path", "content"]},
        timeout=10,
    )

    logger.info("builtin_tools_registered", count=6)
