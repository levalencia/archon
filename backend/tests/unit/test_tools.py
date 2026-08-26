"""Tests for SecureToolRegistry: permissions, timeout, audit, validation."""

from __future__ import annotations

import asyncio

import pytest

from app.agents.protocols import ToolExecutor
from app.runtime.models import ToolCall
from app.security.policy import RiskClass
from app.tools.registry import SecureToolRegistry


class SimplePermissions:
    """Test permission checker."""

    def __init__(self, allowed: bool = True) -> None:
        self._allowed = allowed
        self.checks: list[dict] = []

    async def check(self, agent_id: str, resource: str, action: str, **kwargs: object) -> bool:
        self.checks.append({"agent_id": agent_id, "resource": resource, "action": action})
        return self._allowed


class SimpleAudit:
    """Test audit logger."""

    def __init__(self) -> None:
        self.entries: list[dict] = []

    async def log(self, **kwargs: object) -> None:
        self.entries.append(dict(kwargs))


def sync_tool(query: str) -> dict:
    """A synchronous tool for testing."""
    return {"result": f"Found: {query}"}


async def async_tool(query: str) -> dict:
    """An async tool for testing."""
    return {"result": f"Async found: {query}"}


async def slow_tool(seconds: float = 5.0) -> dict:
    """A tool that takes too long."""
    await asyncio.sleep(seconds)
    return {"result": "finally done"}


def failing_tool() -> dict:
    """A tool that raises an exception."""
    msg = "Database connection failed"
    raise ConnectionError(msg)


class TestToolRegistration:
    """Tool registration and listing."""

    @pytest.mark.unit
    def test_satisfies_protocol(self) -> None:
        registry = SecureToolRegistry()
        assert isinstance(registry, ToolExecutor)

    @pytest.mark.unit
    def test_register_and_list(self) -> None:
        registry = SecureToolRegistry()
        registry.register("search", sync_tool, description="Search the web")
        registry.register("calculate", sync_tool, description="Do math")

        tools = registry.list_tools()
        assert len(tools) == 2
        names = [t["name"] for t in tools]
        assert "search" in names
        assert "calculate" in names

    @pytest.mark.unit
    def test_get_tool(self) -> None:
        registry = SecureToolRegistry()
        registry.register("search", sync_tool, description="Search")

        tool = registry.get_tool("search")
        assert tool is not None
        assert tool.name == "search"

    @pytest.mark.unit
    def test_get_nonexistent_tool(self) -> None:
        registry = SecureToolRegistry()
        assert registry.get_tool("nope") is None


class TestToolExecution:
    """Tool execution with sync and async handlers."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_execute_sync_tool(self) -> None:
        registry = SecureToolRegistry()
        registry.register("search", sync_tool, input_schema={"required": ["query"]})

        result = await registry.execute("search", {"query": "weather"})
        assert result["result"] == "Found: weather"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_execute_async_tool(self) -> None:
        registry = SecureToolRegistry()
        registry.register("search", async_tool, input_schema={"required": ["query"]})

        result = await registry.execute("search", {"query": "news"})
        assert result["result"] == "Async found: news"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_unknown_tool_raises(self) -> None:
        registry = SecureToolRegistry()

        with pytest.raises(ValueError, match="Unknown tool"):
            await registry.execute("nonexistent", {})

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tool_error_propagates(self) -> None:
        registry = SecureToolRegistry()
        registry.register("broken", failing_tool)

        with pytest.raises(ConnectionError, match="Database connection"):
            await registry.execute("broken", {})


class TestToolTimeout:
    """Timeout enforcement via asyncio.wait_for."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_timeout_enforcement(self) -> None:
        registry = SecureToolRegistry()
        registry.register("slow", slow_tool, input_schema={"required": ["seconds"]}, timeout=1)

        with pytest.raises(TimeoutError, match="timed out"):
            await registry.execute("slow", {"seconds": 10.0})

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_fast_tool_within_timeout(self) -> None:
        registry = SecureToolRegistry()
        registry.register("fast", async_tool, input_schema={"required": ["query"]}, timeout=5)

        result = await registry.execute("fast", {"query": "quick"})
        assert result["result"] == "Async found: quick"


class TestToolPermissions:
    """Permission gating before execution."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_allowed_permission(self) -> None:
        perms = SimplePermissions(allowed=True)
        registry = SecureToolRegistry(permissions=perms)
        registry.register(
            "search",
            sync_tool,
            required_permissions=["read"],
            input_schema={"required": ["query"]},
        )

        result = await registry.execute("search", {"query": "test"})
        assert result["result"] == "Found: test"
        assert len(perms.checks) == 1

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_denied_permission_raises(self) -> None:
        perms = SimplePermissions(allowed=False)
        registry = SecureToolRegistry(permissions=perms)
        registry.register(
            "search",
            sync_tool,
            required_permissions=["read"],
            input_schema={"required": ["query"]},
        )

        with pytest.raises(PermissionError, match="Permission denied"):
            await registry.execute("search", {"query": "test"})

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_no_permissions_required_skips_check(self) -> None:
        perms = SimplePermissions(allowed=False)
        registry = SecureToolRegistry(permissions=perms)
        registry.register(
            "search", sync_tool, input_schema={"required": ["query"]}
        )  # No required_permissions

        result = await registry.execute("search", {"query": "test"})
        assert result["result"] == "Found: test"
        assert len(perms.checks) == 0  # No check made


class TestToolInputValidation:
    """Input schema validation."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_missing_required_field(self) -> None:
        registry = SecureToolRegistry()
        registry.register(
            "search",
            sync_tool,
            input_schema={"required": ["query"]},
        )

        with pytest.raises(ValueError, match="Missing required parameter: query"):
            await registry.execute("search", {})

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_valid_input_passes(self) -> None:
        registry = SecureToolRegistry()
        registry.register(
            "search",
            sync_tool,
            input_schema={"required": ["query"]},
        )

        result = await registry.execute("search", {"query": "test"})
        assert result["result"] == "Found: test"

    @pytest.mark.unit
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("tool_name", "field", "field_schema", "invalid_value"),
        [
            ("read_file", "max_size", {"type": "integer"}, "classified-max-size"),
            ("web_search", "num_results", {"type": "integer"}, "classified-count"),
            ("web_search", "num_results", {"type": "integer"}, True),
            (
                "memory",
                "action",
                {"type": "string", "enum": ["add", "remove", "replace", "list"]},
                "classified-invalid-action",
            ),
        ],
    )
    async def test_invalid_types_and_enums_fail_before_all_hooks(
        self,
        tool_name: str,
        field: str,
        field_schema: dict[str, object],
        invalid_value: object,
    ) -> None:
        events: list[str] = []

        class Permissions:
            async def check(self, **_arguments: object) -> bool:
                events.append("permission")
                return True

        def resolver(_arguments: object) -> tuple[object, ...]:
            events.append("resolver")
            return ()

        async def handler(**_arguments: object) -> dict[str, bool]:
            events.append("handler")
            return {"ok": True}

        registry = SecureToolRegistry(permissions=Permissions())  # type: ignore[arg-type]
        registry.register(
            tool_name,
            handler,
            required_permissions=["use"],
            input_schema={"properties": {field: field_schema}},
            risk_classes=frozenset({RiskClass.READ}),
            resource_resolver=resolver,  # type: ignore[arg-type]
        )

        for operation in (
            lambda: registry.policy_request(ToolCall("call-1", tool_name, {field: invalid_value})),
            lambda: registry.execute(tool_name, {field: invalid_value}),
        ):
            with pytest.raises(ValueError, match=f"Invalid parameter: {field}") as captured:
                result = operation()
                if asyncio.iscoroutine(result):
                    await result
            assert str(invalid_value) not in str(captured.value)

        assert events == []

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_valid_optional_supported_types_and_enum_pass(self) -> None:
        seen: list[dict[str, object]] = []

        async def handler(**arguments: object) -> dict[str, bool]:
            seen.append(arguments)
            return {"ok": True}

        registry = SecureToolRegistry()
        registry.register(
            "typed",
            handler,
            input_schema={
                "properties": {
                    "text": {"type": "string", "enum": ["safe"]},
                    "count": {"type": "integer"},
                    "ratio": {"type": "number"},
                    "enabled": {"type": "boolean"},
                    "metadata": {"type": "object"},
                    "items": {"type": "array"},
                }
            },
        )
        arguments = {
            "text": "safe",
            "count": 2,
            "ratio": 1.5,
            "enabled": True,
            "metadata": {"nested": "value"},
            "items": ("one", "two"),
        }

        assert await registry.execute("typed", arguments) == {"ok": True}
        assert seen == [arguments]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_number_must_be_finite_and_enum_equality_is_type_sensitive(self) -> None:
        registry = SecureToolRegistry()
        registry.register(
            "typed",
            lambda **_arguments: {"ok": True},
            input_schema={
                "properties": {
                    "amount": {"type": "number", "enum": [1]},
                    "ratio": {"type": "number"},
                }
            },
        )

        for arguments in ({"amount": 1.0}, {"ratio": float("inf")}, {"ratio": float("nan")}):
            with pytest.raises(ValueError, match="Invalid parameter"):
                await registry.execute("typed", arguments)

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "schema",
        [
            {"required": "query"},
            {"properties": []},
            {"properties": {"query": "string"}},
            {"properties": {"query": {"type": "null"}}},
            {"properties": {"query": {"type": "string", "enum": "secret"}}},
            {"properties": {"query": {"type": "integer", "enum": [True]}}},
            {"additionalProperties": "yes"},
        ],
    )
    def test_malformed_trusted_schema_fails_registration(self, schema: dict[str, object]) -> None:
        registry = SecureToolRegistry()

        with pytest.raises((TypeError, ValueError), match="input schema"):
            registry.register("malformed", sync_tool, input_schema=schema)


class TestToolAudit:
    """Audit logging for tool execution."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_success_logged(self) -> None:
        audit = SimpleAudit()
        registry = SecureToolRegistry(audit=audit)
        registry.register("search", sync_tool, input_schema={"required": ["query"]})

        await registry.execute("search", {"query": "test"})

        assert len(audit.entries) == 1
        assert audit.entries[0]["action"] == "tool_executed"
        assert audit.entries[0]["result"] == "success"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_permission_denied_logged(self) -> None:
        perms = SimplePermissions(allowed=False)
        audit = SimpleAudit()
        registry = SecureToolRegistry(permissions=perms, audit=audit)
        registry.register(
            "search",
            sync_tool,
            required_permissions=["read"],
            input_schema={"required": ["query"]},
        )

        with pytest.raises(PermissionError):
            await registry.execute("search", {"query": "test"})

        assert len(audit.entries) == 1
        assert audit.entries[0]["action"] == "permission_denied"
        assert audit.entries[0]["security_level"] == "warning"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_timeout_logged(self) -> None:
        audit = SimpleAudit()
        registry = SecureToolRegistry(audit=audit)
        registry.register("slow", slow_tool, input_schema={"required": ["seconds"]}, timeout=1)

        with pytest.raises(TimeoutError):
            await registry.execute("slow", {"seconds": 10.0})

        assert len(audit.entries) == 1
        assert audit.entries[0]["action"] == "tool_timeout"
        assert audit.entries[0]["security_level"] == "error"
