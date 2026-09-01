from __future__ import annotations

import pytest

from app.capabilities.index import CapabilityIndex
from app.capabilities.models import CapabilityDescriptor, CapabilityKind, PermissionDecision
from app.capabilities.selector import SelectionRequest, select_capabilities

pytestmark = pytest.mark.unit


def cap(
    identifier: str,
    *,
    kind: CapabilityKind = CapabilityKind.SKILL,
    description: str = "",
    triggers: tuple[str, ...] = (),
    negative: tuple[str, ...] = (),
    permissions: tuple[str, ...] = (),
    cost: int = 10,
    priority: int = 0,
) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        id=identifier,
        kind=kind,
        name=identifier,
        description=description,
        triggers=triggers,
        negative_triggers=negative,
        required_permissions=permissions,
        context_cost=cost,
        priority=priority,
        version="1",
        content_hash="a" * 64,
    )


def test_index_supports_all_kinds_and_rejects_duplicate_ids() -> None:
    values = [
        cap("skill", kind=CapabilityKind.SKILL),
        cap("native", kind=CapabilityKind.NATIVE),
        cap("mcp", kind=CapabilityKind.MCP),
    ]
    index = CapabilityIndex(values)
    assert [x.id for x in index.all()] == ["mcp", "native", "skill"]
    with pytest.raises(ValueError, match="duplicate"):
        CapabilityIndex([values[0], values[0]])


def test_deterministic_scoring_reasons_and_tie_breaking() -> None:
    index = CapabilityIndex(
        [
            cap(
                "z-review",
                description="review python code",
                triggers=("code review", "python"),
                priority=1,
            ),
            cap(
                "a-review",
                description="review python code",
                triggers=("code review", "python"),
                priority=1,
            ),
            cap("docs", triggers=("documentation",)),
        ]
    )
    request = SelectionRequest(intent="Please do a Python code review", context_budget=100)
    first = select_capabilities(index, request)
    second = select_capabilities(index, request)
    assert first == second
    assert [x.descriptor.id for x in first.selected] == ["a-review", "z-review"]
    assert first.selected[0].score > 0
    assert "trigger:code review" in first.selected[0].reasons
    assert [x.descriptor.id for x in first.rejected] == ["docs"]
    assert first.rejected[0].reasons == ("not_relevant",)


def test_negative_trigger_prevents_selection_even_with_positive_match_and_pin() -> None:
    index = CapabilityIndex([cap("review", triggers=("review",), negative=("do not review",))])
    result = select_capabilities(
        index,
        SelectionRequest(
            intent="do not review this", pinned_ids=frozenset({"review"}), context_budget=100
        ),
    )
    assert result.selected == ()
    assert result.rejected[0].reasons == ("negative_trigger:do not review",)


def test_denied_capabilities_are_invisible_before_selection() -> None:
    index = CapabilityIndex(
        [
            cap("safe", triggers=("deploy",), permissions=("read",)),
            cap(
                "secret-deploy",
                kind=CapabilityKind.MCP,
                triggers=("deploy",),
                permissions=("network",),
            ),
        ]
    )
    result = select_capabilities(
        index,
        SelectionRequest(
            intent="deploy",
            permission_decisions={
                "read": PermissionDecision.ALLOW,
                "network": PermissionDecision.DENY,
            },
            context_budget=100,
        ),
    )
    assert [x.descriptor.id for x in result.selected] == ["safe"]
    assert all(x.descriptor.id != "secret-deploy" for x in (*result.selected, *result.rejected))
    assert result.hidden_ids == ("secret-deploy",)


def test_required_permission_is_default_deny_when_policy_is_absent() -> None:
    index = CapabilityIndex([cap("network-tool", triggers=("fetch",), permissions=("network",))])
    result = select_capabilities(index, SelectionRequest(intent="fetch", context_budget=100))
    assert result.selected == result.rejected == ()
    assert result.hidden_ids == ("network-tool",)


def test_ask_is_visible_and_selected_with_approval_reason() -> None:
    index = CapabilityIndex([cap("write", triggers=("format",), permissions=("write",))])
    result = select_capabilities(
        index,
        SelectionRequest(
            intent="format code", permission_decisions={"write": "ask"}, context_budget=100
        ),
    )
    assert result.selected[0].requires_approval is True
    assert "permission_ask:write" in result.selected[0].reasons


def test_pins_rank_first_but_do_not_bypass_policy_negative_or_budget() -> None:
    index = CapabilityIndex(
        [cap("auto", triggers=("test",), cost=5), cap("pin", cost=7), cap("too-big", cost=100)]
    )
    result = select_capabilities(
        index,
        SelectionRequest(
            intent="test", pinned_ids=frozenset({"pin", "too-big"}), context_budget=12
        ),
    )
    assert [x.descriptor.id for x in result.selected] == ["pin", "auto"]
    assert result.context_cost == 12
    assert next(x for x in result.rejected if x.descriptor.id == "too-big").reasons == (
        "context_budget",
    )


def test_path_scope_and_limit_are_deterministic() -> None:
    index = CapabilityIndex(
        [
            cap("global", triggers=("build",), cost=1),
            CapabilityDescriptor(
                id="web",
                kind="native",
                name="web",
                description="",
                triggers=("build",),
                path_scopes=("src/web",),
                context_cost=1,
            ),
            CapabilityDescriptor(
                id="api",
                kind="native",
                name="api",
                description="",
                triggers=("build",),
                path_scopes=("src/api",),
                context_cost=1,
            ),
        ]
    )
    result = select_capabilities(
        index,
        SelectionRequest(
            intent="build", current_path="src/web/page.py", context_budget=10, limit=1
        ),
    )
    assert [x.descriptor.id for x in result.selected] == ["web"]
    assert next(x for x in result.rejected if x.descriptor.id == "api").reasons == ("path_scope",)
