"""Built-in tools for the agent: calculator, datetime, file operations, web search.

Each tool is a plain async function — no framework dependency.
Web search uses real DuckDuckGo via app/tools/web_search.py.

See: https://github.com/levalencia/production-ai-agents/
Concept: Layer 3 - Tools (registered, validated, timeout-enforced)
"""

from __future__ import annotations

import ast
import math
import operator
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

import structlog

from app.tools.memory_tools import memory_tool, session_search_tool  # noqa: F401 — re-exported
from app.tools.web_search import web_search_tool

logger = structlog.get_logger()

MAX_READ_FILE_BYTES = 1_000_000
MAX_CALCULATOR_EXPRESSION_LENGTH = 500
MAX_CALCULATOR_NODES = 64

_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}
_UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCTIONS = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "abs": abs,
    "round": round,
}
_CONSTANTS = {"pi": math.pi, "e": math.e}


def _evaluate_math_node(node: ast.AST) -> int | float:
    """Evaluate a parsed expression containing only explicitly allowed math nodes."""
    if isinstance(node, ast.Expression):
        return _evaluate_math_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("Only numeric constants are supported")
        return node.value
    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
        return _CONSTANTS[node.id]
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return _UNARY_OPERATORS[type(node.op)](_evaluate_math_node(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _evaluate_math_node(node.left)
        right = _evaluate_math_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("Exponent is too large")
        return _BINARY_OPERATORS[type(node.op)](left, right)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        function = _FUNCTIONS.get(node.func.id)
        if function is not None and not node.keywords and 1 <= len(node.args) <= 2:
            return function(*(_evaluate_math_node(argument) for argument in node.args))
    raise ValueError(f"Unsupported expression element: {type(node).__name__}")


async def calculator_tool(expression: str) -> dict:
    """Evaluate a mathematical expression safely.

    Supports: +, -, *, /, **, sqrt, sin, cos, tan, log, pi, e
    Does NOT use eval() — parses and computes safely.
    """
    clean = expression.strip()
    clean = clean.replace("^", "**")

    try:
        if not clean or len(clean) > MAX_CALCULATOR_EXPRESSION_LENGTH:
            raise ValueError("Expression is empty or too long")
        tree = ast.parse(clean, mode="eval")
        if sum(1 for _ in ast.walk(tree)) > MAX_CALCULATOR_NODES:
            raise ValueError("Expression is too complex")
        result = _evaluate_math_node(tree)
        return {"result": float(result), "expression": expression}
    except (ArithmeticError, RecursionError, SyntaxError, TypeError, ValueError) as e:
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


async def read_file_tool(
    path: str | Path, workspace_root: str | Path | None = None, max_size: int = MAX_READ_FILE_BYTES
) -> dict:
    """Read a regular file contained by the configured workspace root."""
    root = Path(workspace_root or os.environ.get("ARCHON_WORKSPACE_ROOT", Path.cwd())).resolve()
    try:
        requested = Path(path)
        candidate = requested if requested.is_absolute() else root / requested
        file_path = candidate.resolve(strict=True)
        file_path.relative_to(root)
        file_stat = file_path.stat()
        if not stat.S_ISREG(file_stat.st_mode):
            return {"error": f"Not a regular file: {path}"}
        if file_stat.st_size > max_size:
            return {"error": f"File exceeds maximum size of {max_size} bytes: {path}"}
        content = file_path.read_text(encoding="utf-8")
        return {"content": content, "path": str(file_path), "size": file_stat.st_size}
    except (FileNotFoundError, RuntimeError):
        return {"error": f"File not found: {path}"}
    except ValueError:
        return {"error": f"Path is outside workspace: {path}"}
    except (OSError, UnicodeError) as e:
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
