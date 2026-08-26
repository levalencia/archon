"""Typed policy metadata bridge tests for SecureToolRegistry."""

from __future__ import annotations

import os
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app.routes import chat as chat_module
from app.routes.chat import _create_tool_registry
from app.runtime.models import ToolCall
from app.security.policy import ResourceKind, ResourcePattern, RiskClass, canonical_tool_name
from app.tools import image_gen as image_gen_module
from app.tools import memory_tools, web_search
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
    def test_tool_name_helper_matches_policy_canonicalization(self) -> None:
        assert canonical_tool_name("  CAFE\u0301  ") == "café"
        with pytest.raises(ValueError, match="control characters"):
            canonical_tool_name("read_file\n")

    def test_definition_is_deeply_immutable_and_copies_inputs(self) -> None:
        permissions = ["read"]
        schema = {"required": ["path"], "properties": {"path": {"type": "string"}}}
        definition = ToolDefinition(
            "READ_FILE", _handler, required_permissions=permissions, input_schema=schema
        )
        permissions.append("write")
        schema["required"].append("secret")

        assert definition.name == "read_file"
        assert definition.required_permissions == ("read",)
        assert tuple(definition.input_schema["required"]) == ("path",)
        assert not hasattr(definition, "__dict__")
        with pytest.raises(FrozenInstanceError):
            definition.description = "changed"  # type: ignore[misc]
        with pytest.raises(TypeError):
            definition.input_schema["new"] = {}  # type: ignore[index]
        with pytest.raises(TypeError):
            definition.input_schema["properties"]["path"]["type"] = "number"  # type: ignore[index]

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
    @pytest.mark.parametrize(
        ("tool_name", "arguments"),
        [
            ("read_file", {"path": "/etc/passwd", "workspace_root": "/"}),
            ("list_directory", {"path": "/etc", "workspace_root": "/"}),
            (
                "write_file",
                {"path": "/tmp/registry-escape", "content": "blocked", "workspace_root": "/"},
            ),
        ],
    )
    def test_live_file_policy_rejects_workspace_root_override_before_resolver(
        self, tool_name: str, arguments: dict[str, object]
    ) -> None:
        registry = SecureToolRegistry()
        register_builtin_tools(registry)

        with pytest.raises(ValueError, match="Unexpected parameter") as captured:
            registry.policy_request(ToolCall("call-1", tool_name, arguments))

        assert "/" not in str(captured.value)

    async def test_policy_and_execute_share_validation_and_validated_parameters(self) -> None:
        resolver_seen: list[dict[str, object]] = []
        handler_seen: list[dict[str, object]] = []

        def resolver(arguments: object) -> tuple[ResourcePattern, ...]:
            resolver_seen.append(dict(arguments))  # type: ignore[arg-type]
            return ()

        async def handler(**arguments: object) -> dict[str, bool]:
            handler_seen.append(arguments)
            return {"ok": True}

        registry = SecureToolRegistry()
        registry.register(
            "reader",
            handler,
            input_schema={
                "required": ["path"],
                "properties": {"path": {"type": "string"}, "encoding": {"type": "string"}},
            },
            risk_classes=frozenset({RiskClass.READ}),
            resource_resolver=resolver,
        )
        call = ToolCall("call-1", "reader", {"path": "notes.txt", "encoding": "utf-8"})

        registry.policy_request(call)
        assert await registry.execute(call) == {"ok": True}
        assert resolver_seen == handler_seen == [{"path": "notes.txt", "encoding": "utf-8"}]

    async def test_unexpected_arguments_fail_before_every_security_and_execution_hook(self) -> None:
        events: list[str] = []

        class Permissions:
            async def check(self, **_arguments: object) -> bool:
                events.append("permission")
                return True

        def resolver(_arguments: object) -> tuple[ResourcePattern, ...]:
            events.append("resolver")
            return ()

        async def handler(path: str) -> dict[str, str]:
            events.append("handler")
            return {"path": path}

        registry = SecureToolRegistry(permissions=Permissions())  # type: ignore[arg-type]
        registry.register(
            "reader",
            handler,
            required_permissions=["read"],
            input_schema={"required": ["path"]},
            risk_classes=frozenset({RiskClass.READ}),
            resource_resolver=resolver,
        )
        secret = "classified-value"
        call = ToolCall("call-1", "reader", {"path": "notes.txt", "extra": secret})

        with pytest.raises(ValueError, match="Unexpected parameter") as policy_error:
            registry.policy_request(call)
        with pytest.raises(ValueError, match="Unexpected parameter") as execute_error:
            await registry.execute(call)

        assert secret not in str(policy_error.value)
        assert secret not in str(execute_error.value)
        assert events == []

    async def test_explicit_additional_properties_true_allows_extra_arguments(self) -> None:
        registry = SecureToolRegistry()
        registry.register(
            "legacy",
            _handler,
            input_schema={"additionalProperties": True},
            risk_classes=frozenset({RiskClass.READ}),
            resource_resolver=lambda arguments: () if arguments["extra"] == "allowed" else (),
        )
        call = ToolCall("call-1", "legacy", {"extra": "allowed"})

        assert registry.policy_request(call).tool_name == "legacy"
        assert await registry.execute(call) == {"ok": True}

    def test_registration_and_all_lookups_use_canonical_tool_identity(self) -> None:
        registry = SecureToolRegistry()
        registry.register("  CAFE\u0301  ", _handler, risk_classes=frozenset({RiskClass.READ}))

        assert registry.get_tool("CAFÉ").name == "café"  # type: ignore[union-attr]
        assert registry.tool_requires_approval(" café ") is False
        assert registry.policy_request(ToolCall("call-1", "CAFÉ", {})).tool_name == "café"

    async def test_execute_uses_canonical_tool_identity(self) -> None:
        registry = SecureToolRegistry()
        registry.register(" Read_File ", _handler)
        assert await registry.execute(ToolCall("call-1", "READ_FILE", {})) == {"ok": True}
        assert await registry.execute(" read_file ") == {"ok": True}

    def test_duplicate_raw_and_canonical_registrations_are_rejected(self) -> None:
        registry = SecureToolRegistry()
        registry.register("Read_File", _handler)
        with pytest.raises(ValueError, match="already registered.*read_file"):
            registry.register("Read_File", _handler)
        with pytest.raises(ValueError, match="already registered.*read_file"):
            registry.register(" read_file ", _handler)

    def test_metadata_views_are_defensive_deep_copies(self) -> None:
        registry = SecureToolRegistry()
        registry.register(
            "reader",
            _handler,
            input_schema={"required": ["path"], "properties": {"path": {"type": "string"}}},
        )
        listed = registry.list_tools()[0]
        listed["input_schema"]["required"].append("secret")
        listed["input_schema"]["properties"]["path"]["type"] = "number"
        provider = registry.definitions()[0]
        provider.input_schema["properties"]["path"]["type"] = "boolean"  # type: ignore[index]

        again = registry.list_tools()[0]["input_schema"]
        assert again["required"] == ["path"]
        assert again["properties"]["path"]["type"] == "string"

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
            input_schema={"required": ["url"]},
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
            input_schema={"required": ["path"]},
            risk_classes=frozenset({RiskClass.READ}),
            resource_resolver=lambda _arguments: result,  # type: ignore[return-value]
        )
        with pytest.raises(
            PolicyMetadataError, match="resource resolver failed for tool 'read_file'"
        ):
            registry.policy_request(ToolCall("call-1", "read_file", {"path": "file"}))

    def test_resolver_error_is_wrapped_and_fails_closed(self) -> None:
        def broken(_arguments: object) -> tuple[ResourcePattern, ...]:
            raise RuntimeError("secret implementation detail")

        registry = SecureToolRegistry()
        registry.register(
            "read_file",
            _handler,
            input_schema={"required": ["path"]},
            risk_classes=frozenset({RiskClass.READ}),
            resource_resolver=broken,
        )
        with pytest.raises(
            PolicyMetadataError, match="resource resolver failed for tool 'read_file'"
        ):
            registry.policy_request(ToolCall("call-1", "read_file", {"path": "file"}))

    def test_resolver_receives_deeply_immutable_copy_and_cannot_mutate_call(self) -> None:
        original = {"nested": {"tokens": ["safe"]}}

        def mutating(arguments: object) -> tuple[ResourcePattern, ...]:
            arguments["nested"]["tokens"].append("changed")  # type: ignore[index,union-attr]
            return ()

        registry = SecureToolRegistry()
        registry.register(
            "reader",
            _handler,
            input_schema={"required": ["nested"]},
            risk_classes=frozenset({RiskClass.READ}),
            resource_resolver=mutating,
        )
        call = ToolCall("call-1", "reader", original)
        with pytest.raises(
            PolicyMetadataError, match="^resource resolver failed for tool 'reader'$"
        ):
            registry.policy_request(call)
        assert original == {"nested": {"tokens": ["safe"]}}
        assert call.arguments["nested"] == {"tokens": ["safe"]}

    def test_resolver_exception_message_is_stable_and_does_not_leak_secrets(self) -> None:
        secret = "classified-api-token"

        def broken(arguments: object) -> tuple[ResourcePattern, ...]:
            raise RuntimeError(f"backend failed with {arguments!r} and {secret}")

        registry = SecureToolRegistry()
        registry.register(
            "fetch",
            _handler,
            input_schema={"required": ["token"]},
            risk_classes=frozenset({RiskClass.NETWORK}),
            resource_resolver=broken,
        )
        with pytest.raises(PolicyMetadataError) as captured:
            registry.policy_request(ToolCall("call-1", "FETCH", {"token": secret}))
        assert str(captured.value) == "resource resolver failed for tool 'fetch'"
        assert secret not in str(captured.value)

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
        with pytest.raises(
            PolicyMetadataError, match="resource resolver failed for tool 'safe_name'"
        ):
            registry.policy_request(ToolCall("call-1", "safe_name", {}))

    async def test_unclassified_legacy_registration_and_execution_remain_compatible(
        self,
    ) -> None:
        resolver_calls: list[object] = []

        def resolver(arguments: object) -> tuple[ResourcePattern, ...]:
            resolver_calls.append(arguments)
            return ()

        registry = SecureToolRegistry()
        registry.register(
            "legacy",
            _handler,
            input_schema={"additionalProperties": True},
            resource_resolver=resolver,
        )
        secret = "do-not-leak-this-token"
        call = ToolCall("call-1", "legacy", {"token": secret})

        with pytest.raises(PolicyMetadataError) as error:
            registry.policy_request(call)

        assert "legacy" in str(error.value)
        assert secret not in str(error.value)
        assert resolver_calls == []
        assert await registry.execute(call) == {"ok": True}

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
    @pytest.mark.skipif(os.name == "nt", reason="Backslash is a Windows path separator")
    def test_rejects_backslash_identity_mismatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "workspace"
        root.mkdir()
        monkeypatch.setenv("ARCHON_WORKSPACE_ROOT", str(root))

        with pytest.raises(ValueError, match="^Invalid workspace path$"):
            resolve_workspace_path({"path": r"allowed\secret.txt"})

    @pytest.mark.skipif(os.name == "nt", reason="Backslash is a Windows path separator")
    @pytest.mark.parametrize("tool_name", ["read_file", "list_directory", "write_file"])
    def test_file_tool_policy_rejects_backslash_with_sanitized_error(self, tool_name: str) -> None:
        registry = SecureToolRegistry()
        register_builtin_tools(registry)

        arguments = {"path": r"allowed\secret.txt"}
        if tool_name == "write_file":
            arguments["content"] = "blocked"
        with pytest.raises(PolicyMetadataError) as captured:
            registry.policy_request(ToolCall("call-1", tool_name, arguments))

        assert str(captured.value) == f"resource resolver failed for tool '{tool_name}'"
        assert r"allowed\secret.txt" not in str(captured.value)

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

    def test_ignores_untrusted_workspace_root_argument(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "workspace"
        root.mkdir()
        monkeypatch.setenv("ARCHON_WORKSPACE_ROOT", str(root))

        resolved = resolve_workspace_path({"path": "file.txt", "workspace_root": "/"})

        assert resolved == (ResourcePattern(ResourceKind.PATH, str(root / "file.txt")),)

    @pytest.mark.parametrize("arguments", [{}, {"path": 123}])
    def test_requires_a_string_path(self, arguments: dict[str, object]) -> None:
        with pytest.raises(ValueError, match="path.*string"):
            resolve_workspace_path(arguments)


class TestLiveClassifications:
    @pytest.mark.parametrize(
        ("tool_name", "arguments"),
        [
            ("web_search", {"query": "policy", "num_results": 2, "max_results": 1}),
            ("read_file", {"path": "notes.txt", "max_size": 1024}),
            ("image_gen", {"prompt": "a blue square", "provider": "mock", "size": "8x8"}),
            ("session_search", {"query": "policy", "limit": 2}),
            ("memory", {"action": "replace", "old_text": "old", "content": "new"}),
            ("background_task", {"action": "status", "task_id": "task-1"}),
        ],
    )
    def test_live_optional_schema_fields_pass_policy_validation(
        self, tool_name: str, arguments: dict[str, object]
    ) -> None:
        request = _create_tool_registry().policy_request(ToolCall("call-1", tool_name, arguments))
        assert request.tool_name == tool_name

    async def test_safe_optional_fields_reach_deterministic_live_handlers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "notes.txt").write_text("hello", encoding="utf-8")
        monkeypatch.setenv("ARCHON_WORKSPACE_ROOT", str(workspace))
        monkeypatch.delenv("ARCHON_BRAVE_API_KEY", raising=False)

        async def fake_search(query: str, num: int) -> list[dict[str, str]]:
            return [{"title": query, "url": "https://example.test", "snippet": str(num)}]

        async def fake_extract(results: list[dict[str, str]]) -> list[dict[str, str]]:
            return results

        class Store:
            def search(self, query: str, limit: int) -> list[dict[str, object]]:
                return [{"query": query, "limit": limit}]

        monkeypatch.setattr(web_search, "_searxng_search", fake_search)
        monkeypatch.setattr(web_search, "_extract_content", fake_extract)
        monkeypatch.setattr(memory_tools, "get_session_store", lambda: Store())
        monkeypatch.setattr(image_gen_module, "image_path", lambda filename: tmp_path / filename)
        registry = _create_tool_registry()

        searched = await registry.execute(
            ToolCall("search", "web_search", {"query": "policy", "max_results": 2})
        )
        read = await registry.execute(
            ToolCall("read", "read_file", {"path": "notes.txt", "max_size": 5})
        )
        image = await registry.execute(
            ToolCall(
                "image",
                "image_gen",
                {"prompt": "a blue square", "provider": "mock", "size": "8x8"},
            )
        )
        sessions = await registry.execute(
            ToolCall("sessions", "session_search", {"query": "policy", "limit": 2})
        )

        assert searched["results"][0]["snippet"] == "2"
        assert read["content"] == "hello"
        assert image["size"] == "8x8"
        assert '"limit": 2' in sessions["result"]

    @pytest.mark.parametrize(
        ("tool_name", "arguments", "forbidden_name", "secret"),
        [
            ("image_gen", {"prompt": "cat", "api_key": "***"}, "api_key", "***"),
            (
                "read_file",
                {"path": "notes.txt", "workspace_root": "/secret/root"},
                "workspace_root",
                "/secret/root",
            ),
        ],
    )
    async def test_sensitive_live_arguments_are_rejected_before_hooks_and_handler(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tool_name: str,
        arguments: dict[str, object],
        forbidden_name: str,
        secret: str,
    ) -> None:
        events: list[str] = []

        async def handler(**_arguments: object) -> dict[str, bool]:
            events.append("handler")
            return {"ok": True}

        def resolver(_arguments: object) -> tuple[ResourcePattern, ...]:
            events.append("resolver")
            return ()

        monkeypatch.setattr(chat_module, f"{tool_name}_tool", handler)
        if tool_name == "read_file":
            monkeypatch.setattr(chat_module, "resolve_workspace_path", resolver)
        registry = _create_tool_registry()
        call = ToolCall("call-1", tool_name, arguments)

        with pytest.raises(ValueError, match="Unexpected parameter") as policy_error:
            registry.policy_request(call)
        with pytest.raises(ValueError, match="Unexpected parameter") as execute_error:
            await registry.execute(call)

        for error in (policy_error.value, execute_error.value):
            assert forbidden_name not in str(error)
            assert secret not in str(error)
        assert events == []

    def test_optional_argument_schemas_declare_types_and_remain_closed(self) -> None:
        live = {tool["name"]: tool["input_schema"] for tool in _create_tool_registry().list_tools()}
        expected_live = {
            "web_search": {
                "query": {"type": "string"},
                "num_results": {"type": "integer"},
                "max_results": {"type": "integer"},
            },
            "read_file": {"path": {"type": "string"}, "max_size": {"type": "integer"}},
            "image_gen": {
                "prompt": {"type": "string"},
                "provider": {"type": "string"},
                "size": {"type": "string"},
            },
            "session_search": {"query": {"type": "string"}, "limit": {"type": "integer"}},
        }

        for name, properties in expected_live.items():
            assert live[name]["properties"] == properties
            assert live[name].get("additionalProperties", False) is False

        builtins = SecureToolRegistry()
        register_builtin_tools(builtins)
        builtin_schemas = {tool["name"]: tool["input_schema"] for tool in builtins.list_tools()}
        assert builtin_schemas["web_search"]["properties"] == expected_live["web_search"]
        assert builtin_schemas["read_file"]["properties"] == expected_live["read_file"]
        assert builtin_schemas["web_search"].get("additionalProperties", False) is False
        assert builtin_schemas["read_file"].get("additionalProperties", False) is False
        assert (
            builtins.policy_request(
                ToolCall("search", "web_search", {"query": "policy", "num_results": 2})
            ).tool_name
            == "web_search"
        )
        assert (
            builtins.policy_request(
                ToolCall("read", "read_file", {"path": "notes.txt", "max_size": 1024})
            ).tool_name
            == "read_file"
        )

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
