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
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import structlog

from app.security.policy import RiskClass
from app.tools.memory_tools import memory_tool, session_search_tool  # noqa: F401 — re-exported
from app.tools.web_search import web_search_tool

logger = structlog.get_logger()

MAX_READ_FILE_BYTES = 1_000_000
MAX_CALCULATOR_EXPRESSION_LENGTH = 500
MAX_CALCULATOR_NODES = 64


@dataclass(frozen=True, slots=True)
class TenantWorkspace:
    """Trusted descriptor-relative workspace scope created by the HTTP layer."""

    configured_root: Path
    tenant_components: tuple[str, str]

    @property
    def path(self) -> Path:
        return self.configured_root.joinpath(*self.tenant_components)

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


def _workspace_root(workspace_root: str | Path | TenantWorkspace | None = None) -> Path:
    if isinstance(workspace_root, TenantWorkspace):
        return workspace_root.path
    root_value = (
        workspace_root
        if workspace_root is not None
        else os.environ.get("ARCHON_WORKSPACE_ROOT", str(Path.cwd()))
    )
    return Path(root_value).resolve()


def _workspace_anchor(
    workspace_root: str | Path | TenantWorkspace | None,
) -> tuple[Path, list[str]]:
    if isinstance(workspace_root, TenantWorkspace):
        return workspace_root.configured_root, list(workspace_root.tenant_components)
    return _workspace_root(workspace_root), []


_SECURE_TRAVERSAL_AVAILABLE = (
    hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_NOFOLLOW")
    and os.open in os.supports_dir_fd
    and os.mkdir in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.stat in os.supports_follow_symlinks
    and os.listdir in os.supports_fd
)
_DIRECTORY_OPEN_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)


def _relative_workspace_components(
    path: str | Path,
    root: Path,
    workspace_root: str | Path | TenantWorkspace | None,
) -> list[str]:
    """Return lexical path components without resolving any requested component."""
    raw_path = os.fspath(path)
    if not isinstance(raw_path, str):
        raise ValueError("Workspace paths must be text")
    if os.name != "nt" and "\\" in raw_path:
        raise ValueError("Invalid workspace path")
    if not raw_path or any(ord(character) < 32 or ord(character) == 127 for character in raw_path):
        raise ValueError("Invalid workspace path")
    if "//" in raw_path or (raw_path.endswith(os.sep) and raw_path != os.sep):
        raise ValueError("Invalid workspace path component")

    requested = Path(raw_path)
    if requested.is_absolute():
        roots = [root]
        root_value = (
            root
            if isinstance(workspace_root, TenantWorkspace)
            else workspace_root
            if workspace_root is not None
            else os.environ.get("ARCHON_WORKSPACE_ROOT", str(Path.cwd()))
        )
        lexical_root = Path(os.path.abspath(os.fspath(root_value)))
        if lexical_root not in roots:
            roots.append(lexical_root)
        relative: Path | None = None
        matched_root: Path | None = None
        for allowed_root in roots:
            try:
                relative = requested.relative_to(allowed_root)
                matched_root = allowed_root
                break
            except ValueError:
                continue
        if relative is None or matched_root is None:
            raise ValueError("Path is outside workspace")
    else:
        relative = requested
        matched_root = None

    # A single dot names the workspace root for compatibility with the list tool.
    if raw_path == "." or relative == Path("."):
        return []
    raw_components = raw_path.split(os.sep)
    if requested.is_absolute():
        if matched_root is None:  # pragma: no cover - guarded above
            raise ValueError("Path is outside workspace")
        root_prefix = str(matched_root)
        relative_text = raw_path[len(root_prefix) :].removeprefix(os.sep)
        raw_components = relative_text.split(os.sep)
    if any(component in {"", ".", ".."} for component in raw_components):
        raise ValueError("Invalid workspace path component")
    components = list(relative.parts)
    if any(component in {"", ".", ".."} for component in components):
        raise ValueError("Invalid workspace path component")
    return components


def _open_workspace_directory(root: Path, components: list[str], *, create: bool = False) -> int:
    """Open a workspace directory by walking trusted directory descriptors."""
    if not _SECURE_TRAVERSAL_AVAILABLE:
        raise NotImplementedError("Secure workspace traversal is unavailable")

    current_fd = os.open(root, _DIRECTORY_OPEN_FLAGS)
    try:
        for component in components:
            try:
                next_fd = os.open(component, _DIRECTORY_OPEN_FLAGS, dir_fd=current_fd)
            except FileNotFoundError:
                if not create:
                    raise
                with suppress(FileExistsError):
                    os.mkdir(component, mode=0o700, dir_fd=current_fd)
                next_fd = os.open(component, _DIRECTORY_OPEN_FLAGS, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _path_result(root: Path, components: list[str]) -> str:
    return str(root.joinpath(*components))


async def read_file_tool(
    path: str | Path,
    workspace_root: str | Path | TenantWorkspace | None = None,
    max_size: int = MAX_READ_FILE_BYTES,
) -> dict:
    """Read a regular file through a no-follow workspace descriptor chain."""
    directory_fd: int | None = None
    file_fd: int | None = None
    try:
        if type(max_size) is not int or not 0 <= max_size <= MAX_READ_FILE_BYTES:
            return {"error": f"max_size must be between 0 and {MAX_READ_FILE_BYTES} bytes"}
        root = _workspace_root(workspace_root)
        anchor, tenant_components = _workspace_anchor(workspace_root)
        components = _relative_workspace_components(path, root, workspace_root)
        if not components:
            return {"error": f"Not a regular file: {path}"}
        directory_fd = _open_workspace_directory(anchor, tenant_components + components[:-1])
        file_fd = os.open(
            components[-1],
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_fd,
        )
        file_stat = os.fstat(file_fd)
        if not stat.S_ISREG(file_stat.st_mode):
            return {"error": f"Not a regular file: {path}"}
        if file_stat.st_nlink != 1:
            return {"error": f"Unable to read file safely: {path}"}
        if file_stat.st_size > max_size:
            return {"error": f"File exceeds maximum size of {max_size} bytes: {path}"}

        chunks: list[bytes] = []
        remaining = max_size + 1
        while remaining > 0:
            chunk = os.read(file_fd, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content_bytes = b"".join(chunks)
        if len(content_bytes) > max_size:
            return {"error": f"File exceeds maximum size of {max_size} bytes: {path}"}
        content = content_bytes.decode("utf-8")
        return {
            "content": content,
            "path": _path_result(root, components),
            "size": len(content_bytes),
        }
    except FileNotFoundError:
        return {"error": f"File not found: {path}"}
    except NotImplementedError:
        return {"error": "Secure workspace traversal is unavailable"}
    except (RuntimeError, TypeError, ValueError):
        return {"error": f"Path is outside workspace: {path}"}
    except (OSError, UnicodeError):
        return {"error": f"Path is outside workspace: {path}"}
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)


async def list_directory_tool(
    path: str | Path, workspace_root: str | Path | TenantWorkspace | None = None
) -> dict:
    """List a directory through a no-follow workspace descriptor chain."""
    directory_fd: int | None = None
    try:
        root = _workspace_root(workspace_root)
        anchor, tenant_components = _workspace_anchor(workspace_root)
        components = _relative_workspace_components(path, root, workspace_root)
        directory_fd = _open_workspace_directory(anchor, tenant_components + components)
        items = []
        for name in sorted(os.listdir(directory_fd)):
            item_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            items.append(
                {
                    "name": name,
                    "type": (
                        "file"
                        if stat.S_ISREG(item_stat.st_mode)
                        else "directory"
                        if stat.S_ISDIR(item_stat.st_mode)
                        else "symlink"
                        if stat.S_ISLNK(item_stat.st_mode)
                        else "other"
                    ),
                    "size": item_stat.st_size if stat.S_ISREG(item_stat.st_mode) else 0,
                }
            )
        return {"path": _path_result(root, components), "items": items, "count": len(items)}
    except FileNotFoundError:
        return {"error": f"Directory not found: {path}"}
    except NotImplementedError:
        return {"error": "Secure workspace traversal is unavailable"}
    except (RuntimeError, TypeError, ValueError):
        return {"error": f"Path is outside workspace: {path}"}
    except OSError:
        return {"error": f"Path is outside workspace: {path}"}
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


async def write_file_tool(
    path: str | Path,
    content: str,
    workspace_root: str | Path | TenantWorkspace | None = None,
) -> dict:
    """Write a file through a no-follow workspace descriptor chain."""
    directory_fd: int | None = None
    file_fd: int | None = None
    try:
        root = _workspace_root(workspace_root)
        anchor, tenant_components = _workspace_anchor(workspace_root)
        components = _relative_workspace_components(path, root, workspace_root)
        if not components:
            return {"error": f"Not a regular file: {path}"}
        encoded_content = content.encode("utf-8")
        directory_fd = _open_workspace_directory(
            anchor, tenant_components + components[:-1], create=True
        )
        file_fd = os.open(
            components[-1],
            os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
            0o600,
            dir_fd=directory_fd,
        )
        file_stat = os.fstat(file_fd)
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
            return {"error": f"Unable to write file safely: {path}"}
        os.fchmod(file_fd, 0o600)
        os.ftruncate(file_fd, 0)
        written = 0
        while written < len(encoded_content):
            written += os.write(file_fd, encoded_content[written:])
        return {
            "path": _path_result(root, components),
            "size": written,
            "status": "written",
        }
    except FileNotFoundError:
        return {"error": f"Unable to write file safely: {path}"}
    except NotImplementedError:
        return {"error": "Secure workspace traversal is unavailable"}
    except (RuntimeError, TypeError, ValueError):
        return {"error": f"Path is outside workspace: {path}"}
    except (OSError, UnicodeError):
        return {"error": f"Path is outside workspace: {path}"}
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)


def register_builtin_tools(registry: object) -> None:
    """Register all built-in tools with a SecureToolRegistry."""
    from app.tools.registry import SecureToolRegistry, resolve_workspace_path

    if not isinstance(registry, SecureToolRegistry):
        return

    registry.register(
        name="calculator",
        handler=calculator_tool,
        description="Evaluate math expressions (+, -, *, /, sqrt, pi)",
        input_schema={"required": ["expression"]},
        timeout=5,
        risk_classes=frozenset({RiskClass.READ}),
    )
    registry.register(
        name="datetime",
        handler=datetime_tool,
        description="Get current date, time, timestamp info",
        input_schema={"required": ["query"]},
        timeout=5,
        risk_classes=frozenset({RiskClass.READ}),
    )
    registry.register(
        name="web_search",
        handler=web_search_tool,
        description="Search the web for information",
        input_schema={
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "num_results": {"type": "integer"},
                "max_results": {"type": "integer"},
            },
        },
        timeout=30,
        risk_classes=frozenset({RiskClass.NETWORK}),
    )
    registry.register(
        name="read_file",
        handler=read_file_tool,
        description="Read the contents of a file",
        required_permissions=["read_file"],
        input_schema={
            "required": ["path"],
            "properties": {
                "path": {"type": "string"},
                "max_size": {"type": "integer"},
            },
        },
        timeout=10,
        risk_classes=frozenset({RiskClass.READ}),
        resource_resolver=resolve_workspace_path,
    )
    registry.register(
        name="list_directory",
        handler=list_directory_tool,
        description="List files and subdirectories",
        required_permissions=["list_directory"],
        input_schema={"required": ["path"]},
        timeout=10,
        risk_classes=frozenset({RiskClass.READ}),
        resource_resolver=resolve_workspace_path,
    )
    registry.register(
        name="write_file",
        handler=write_file_tool,
        description="Write content to a file",
        required_permissions=["write_file"],
        input_schema={"required": ["path", "content"]},
        timeout=10,
        requires_approval=True,
        risk_classes=frozenset({RiskClass.WRITE}),
        resource_resolver=resolve_workspace_path,
    )
    logger.info("builtin_tools_registered", count=6)
