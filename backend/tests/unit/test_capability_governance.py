from __future__ import annotations

from typing import Any

import pytest

from app.routes.chat import get_tool_registry
from app.tools.registry import SecureToolRegistry

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_disabled_capability_is_removed_before_provider_and_cannot_execute() -> None:
    calls = 0

    async def handler() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"ok": True}

    registry = SecureToolRegistry(disabled_capability_ids=frozenset({"native.hidden"}))
    registry.register("hidden", handler)

    assert registry.list_tools() == []
    assert registry.definitions() == ()
    assert registry.capability_descriptors() == ()
    assert registry.get_tool("hidden") is None
    with pytest.raises(ValueError, match="Unknown tool"):
        await registry.execute("hidden")
    assert calls == 0


@pytest.mark.asyncio
async def test_denied_dependency_filters_and_remove_is_irreversible() -> None:
    registry = SecureToolRegistry(denied_permissions=frozenset({"capability.net.use"}))
    registry.register(
        "networked",
        lambda: None,
        required_permissions=["capability.net.use"],
    )
    assert not registry.list_tools()
    with pytest.raises(ValueError, match="Unknown tool"):
        await registry.execute("networked")
    assert registry.remove_capability("native.networked")
    registry.apply_capability_policy(denied_permissions=frozenset())
    assert registry.get_tool("networked") is None


def test_live_native_inventory_has_safe_stable_execution_mapping() -> None:
    first = get_tool_registry().capability_descriptors()
    second = get_tool_registry().capability_descriptors()
    assert first == second
    assert len(first) >= 9
    assert all(item.id.startswith("native.") for item in first)
    assert all(item.executable_name == item.name for item in first)
    assert len({item.id for item in first}) == len(first)
