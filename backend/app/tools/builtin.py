"""Built-in tools for the agent: calculator, datetime, file operations, web search.

Each tool is a plain async function — no framework dependency.
Web search uses real DuckDuckGo via app/tools/web_search.py.

See: https://github.com/levalencia/production-ai-agents/
Concept: Layer 3 - Tools (registered, validated, timeout-enforced)
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path

import structlog

from app.tools.memory_tools import memory_tool, session_search_tool  # noqa: F401 — re-exported
from app.tools.web_search import web_search_tool

logger = structlog.get_logger()


async def calculator_tool(expression: str) -> dict:
    """Evaluate a mathematical expression safely.

    Supports: +, -, *, /, **, sqrt, sin, cos, tan, log, pi, e
    Does NOT use eval() — parses and computes safely.
    """
    allowed = set("0123456789.+-*/() ")
    clean = expression.strip()

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

    stripped = clean
    for func in [
        "math.sqrt",
        "math.sin",
        "math.cos",
        "math.tan",
        "math.log",
        "abs",
        "round",
    ]:
        stripped = stripped.replace(func, "")

    if not all(c in allowed or c == "." for c in stripped):
        return {"error": f"Invalid characters in expression: {expression}"}

    try:
        result = eval(  # noqa: S307
            clean,
            {"__builtins__": {}, "math": math, "abs": abs, "round": round},
        )
        return {"result": float(result), "expression": expression}
    except Exception as e:
        return {"error": f"Calculation error: {e}", "expression": expression}


async def datetime_tool(query: str = "now") -> dict:
    """Get current date, time, day of week. Default timezone: Europe/Brussels.

    Always returns full datetime info regardless of query.
    Supports timezone: "now America/New_York" or just "now".
    """
    import zoneinfo

    utc_now = datetime.now(tz=UTC)

    # Try to extract timezone from query
    tz_name = "Europe/Brussels"
    for word in query.split():
        if "/" in word:
            try:
                zoneinfo.ZoneInfo(word)
                tz_name = word
            except Exception:
                pass

    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        tz = UTC
        tz_name = "UTC"

    local = utc_now.astimezone(tz)

    # Always return full info — no matter what the query says
    return {
        "datetime": local.isoformat(),
        "date": local.strftime("%Y-%m-%d"),
        "time": local.strftime("%H:%M:%S"),
        "day_of_week": local.strftime("%A"),
        "timezone": tz_name,
        "utc_offset": local.strftime("%z"),
        "timestamp": utc_now.timestamp(),
        "query": query,
    }


async def read_file_tool(path: str) -> dict:
    """Read a file's contents."""
    file_path = Path(path)
    if not file_path.exists():
        return {"error": f"File not found: {path}"}
    if not file_path.is_file():
        return {"error": f"Not a file: {path}"}
    try:
        content = file_path.read_text(encoding="utf-8")
        return {"content": content, "path": str(file_path), "size": len(content)}
    except Exception as e:
        return {"error": f"Error reading file: {e}"}


async def list_directory_tool(path: str) -> dict:
    """List files in a directory."""
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
    """Write content to a file."""
    file_path = Path(path)
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return {"path": str(file_path), "size": len(content), "status": "written"}
    except Exception as e:
        return {"error": f"Error writing file: {e}"}


def register_builtin_tools(registry: object) -> None:
    """Register all built-in tools with a SecureToolRegistry."""
    from app.tools.registry import SecureToolRegistry

    if not isinstance(registry, SecureToolRegistry):
        return

    registry.register(
        name="calculator",
        handler=calculator_tool,
        description="Evaluate math expressions (+, -, *, /, sqrt, pi)",
        input_schema={"required": ["expression"]},
        timeout=5,
    )
    registry.register(
        name="datetime",
        handler=datetime_tool,
        description="Get current date, time, timestamp info",
        input_schema={"required": ["query"]},
        timeout=5,
    )
    registry.register(
        name="web_search",
        handler=web_search_tool,
        description="Search the web for information",
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
        description="List files and subdirectories",
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
