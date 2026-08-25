"""Typed policy metadata bridge tests for SecureToolRegistry."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.routes.chat import _create_tool_registry
from app.runtime.models import ToolCall
from app.security.policy import (
    PolicyAction,
    ResourceKind,
    ResourcePattern,
    RiskClass,
    RulePolicyEngine,
)
from app.tools.builtin import register_builtin_tools
from app.tools.registry import (
    PolicyMetadataError,
    SecureToolRegistry,
    ToolDefinition,
    resolve_workspace_path,
)


def _handler(**_arguments: object) -> dict[str, bool]:
    return {"ok": True}


class TestTypedMetadata:
    def test_definition_keeps_immutable_typed_risks_and_resolver(self) -> None:
        def resolver(_arguments: object) -> tuple[ResourcePattern, ...]:
            return (ResourcePattern(ResourceKind.HOST, "example.com"),)

        definition = ToolDefinition(
            "fetch",
            _handler,
            risk_classes=frozenset({RiskClass.NETWORK}),
            resource_resolver=resolver,
        )

        assert definition.risk_classes == frozenset({RiskClass.NETWORK})
        assert definition.resource_resolver is resolver
        with pytest.raises(AttributeError):
            definition.risk_classes.add(RiskClass.READ)  # type: ignore[attr-defined]

    @pytest.mark.parametrize(
        "risks",
        [
            {RiskClass.READ},
            (RiskClass.READ,),
            frozenset({"read"}),
            "read",
        ],
    )
    def test_risk_classes_require_a_frozenset_of_enum_values(self, risks: object) -> None:
        with pytest.raises(TypeError, match="frozenset.*RiskClass"):
            ToolDefinition("bad", _handler, risk_classes=risks)  # type: ignore[arg-type]

    def test_resource_resolver_must_be_callable(self) -> None:
        with pytest.raises(TypeError, match="resource_resolver must be callable"):
            ToolDefinition("bad", _handler, resource_resolver="path")  # type: ignore[arg-type]


class TestPolicyRequestBridge:
    def test_exact_tool_call_becomes_policy_request(self) -> None:
        resource = ResourcePattern(ResourceKind.HOST, "example.com")
        seen: list[object] = []

        def resolver(arguments: object) -> tuple[ResourcePattern, ...]:
            seen.append(arguments)
            return (resource,)

        registry = SecureToolRegistry()
        registry.register(
            "fetch",
            _handler,
            risk_classes=frozenset({RiskClass.READ, RiskClass.NETWORK}),
            resource_resolver=resolver,
            requires_approval=True,
        )
        call = ToolCall("call-1", "fetch", {"url": "https://example.com"})

        request = registry.policy_request(call)

        assert seen == [call.arguments]
        assert request.tool_name == "fetch"
        assert request.resources == (resource,)
        assert request.risk_classes == frozenset({RiskClass.READ, RiskClass.NETWORK})
        assert request.legacy_requires_approval is True

    def test_unknown_tool_fails_closed(self) -> None:
        with pytest.raises(PolicyMetadataError, match="Unknown tool"):
            SecureToolRegistry().policy_request(ToolCall("call-1", "missing", {}))

    @pytest.mark.parametrize(
        "result",
        [
            [ResourcePattern(ResourceKind.PATH, "/tmp/file")],
            ("/tmp/file",),
        ],
    )
    def test_invalid_resolver_return_fails_closed(self, result: object) -> None:
        registry = SecureToolRegistry()
        registry.register(
            "read_file",
            _handler,
            risk_classes=frozenset({RiskClass.READ}),
            resource_resolver=lambda _arguments: result,  # type: ignore[return-value]
        )
        with pytest.raises(PolicyMetadataError, match="read_file.*tuple.*ResourcePattern"):
            registry.policy_request(ToolCall("call-1", "read_file", {"path": "file"}))

    def test_resolver_error_is_wrapped_and_fails_closed(self) -> None:
        def broken(_arguments: object) -> tuple[ResourcePattern, ...]:
            raise RuntimeError("secret implementation detail")

        registry = SecureToolRegistry()
        registry.register(
            "read_file",
            _handler,
            risk_classes=frozenset({RiskClass.READ}),
            resource_resolver=broken,
        )
        with pytest.raises(
            PolicyMetadataError, match="resource resolver failed for tool 'read_file'"
        ):
            registry.policy_request(ToolCall("call-1", "read_file", {"path": "file"}))

    def test_resolver_cannot_inject_a_second_tool_identity(self) -> None:
        registry = SecureToolRegistry()
        registry.register(
            "safe_name",
            _handler,
            risk_classes=frozenset({RiskClass.READ}),
            resource_resolver=lambda _arguments: (
                ResourcePattern(ResourceKind.TOOL, "different_name"),
            ),
        )
        with pytest.raises(PolicyMetadataError, match="TOOL.*sole tool identity"):
            registry.policy_request(ToolCall("call-1", "safe_name", {}))

    def test_unclassified_legacy_registration_is_constructible_but_denied(self) -> None:
        registry = SecureToolRegistry()
        registry.register("legacy", _handler)

        request = registry.policy_request(ToolCall("call-1", "legacy", {}))

        assert request.risk_classes == frozenset()
        assert RulePolicyEngine([]).evaluate(request).action is PolicyAction.DENY

    def test_list_tools_exposes_only_safe_policy_metadata(self) -> None:
        registry = SecureToolRegistry()
        registry.register(
            "fetch",
            _handler,
            risk_classes=frozenset({RiskClass.NETWORK, RiskClass.READ}),
            resource_resolver=lambda _arguments: (),
            requires_approval=True,
        )

        metadata = registry.list_tools()[0]
        assert metadata["risk_classes"] == ["network", "read"]
        assert metadata["requires_approval"] is True
        assert "resource_resolver" not in metadata


class TestWorkspacePathResolver:
    def test_resolves_relative_and_absolute_paths_from_configured_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "workspace"
        root.mkdir()
        monkeypatch.setenv("ARCHON_WORKSPACE_ROOT", str(root))

        relative = resolve_workspace_path({"path": "nested/../file.txt"})
        absolute = resolve_workspace_path({"path": str(root / "dir" / "item.txt")})

        assert relative == (ResourcePattern(ResourceKind.PATH, str(root / "file.txt")),)
        assert absolute == (ResourcePattern(ResourceKind.PATH, str(root / "dir" / "item.txt")),)

    @pytest.mark.parametrize("arguments", [{}, {"path": 123}])
    def test_requires_a_string_path(self, arguments: dict[str, object]) -> None:
        with pytest.raises(ValueError, match="path.*string"):
            resolve_workspace_path(arguments)


class TestLiveClassifications:
    def test_chat_registry_classifies_every_live_tool(self) -> None:
        registry = _create_tool_registry()
        expected = {
            "calculator": {"read"},
            "datetime": {"read"},
            "web_search": {"network"},
            "read_file": {"read"},
            "write_file": {"write"},
            "image_gen": {"network", "external_side_effect"},
            "memory": {"read", "write"},
            "session_search": {"read"},
            "code_execute": {"execute"},
            "terminal": {"execute"},
            "background_task": {"read"},
        }

        actual = {item["name"]: set(item["risk_classes"]) for item in registry.list_tools()}
        assert actual == expected
        for name in ("read_file", "write_file"):
            assert registry.get_tool(name).resource_resolver is resolve_workspace_path  # type: ignore[union-attr]

    def test_builtin_registry_classifies_every_tool(self) -> None:
        registry = SecureToolRegistry()
        register_builtin_tools(registry)

        expected = {
            "calculator": {"read"},
            "datetime": {"read"},
            "web_search": {"network"},
            "read_file": {"read"},
            "list_directory": {"read"},
            "write_file": {"write"},
        }
        actual = {item["name"]: set(item["risk_classes"]) for item in registry.list_tools()}
        assert actual == expected
        for name in ("read_file", "list_directory", "write_file"):
            assert registry.get_tool(name).resource_resolver is resolve_workspace_path  # type: ignore[union-attr]
