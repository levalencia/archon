"""Unit tests for the pure deterministic policy domain."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.security.policy import (
    ApprovalScope,
    PolicyAction,
    PolicyDecision,
    PolicyRequest,
    PolicyRule,
    ResourceKind,
    ResourcePattern,
    RiskClass,
    RulePolicyEngine,
    arguments_hash,
    canonical_arguments_hash,
)


def resource(kind: ResourceKind, pattern: str) -> ResourcePattern:
    return ResourcePattern(kind, pattern)


def request(
    *resources: ResourcePattern,
    risks: frozenset[RiskClass] = frozenset({RiskClass.READ}),
    legacy: bool = False,
) -> PolicyRequest:
    return PolicyRequest(" Read_File ", resources, risks, legacy)


@pytest.mark.unit
class TestPolicyModels:
    def test_public_enum_values_are_stable(self) -> None:
        assert [action.value for action in PolicyAction] == ["allow", "ask", "deny"]
        assert [scope.value for scope in ApprovalScope] == ["once", "run", "session", "rule"]
        assert [risk.value for risk in RiskClass] == [
            "read",
            "write",
            "execute",
            "network",
            "secret",
            "external_side_effect",
        ]
        assert [kind.value for kind in ResourceKind] == ["tool", "path", "host"]

    def test_models_are_frozen_slotted_and_copy_mutable_inputs(self) -> None:
        resources = [resource(ResourceKind.TOOL, "READ_FILE")]
        risks = {RiskClass.READ}
        rule = PolicyRule("reader", PolicyAction.ALLOW, resources, risks)  # type: ignore[arg-type]
        resources.append(resource(ResourceKind.TOOL, "other"))
        risks.add(RiskClass.WRITE)

        assert rule.resources == (resource(ResourceKind.TOOL, "read_file"),)
        assert rule.risk_classes == frozenset({RiskClass.READ})
        assert not hasattr(rule, "__dict__")
        with pytest.raises(FrozenInstanceError):
            rule.enabled = False  # type: ignore[misc]

    def test_decision_is_immutable(self) -> None:
        decision = PolicyDecision(PolicyAction.ALLOW, frozenset({RiskClass.READ}), None, "safe")
        with pytest.raises(FrozenInstanceError):
            decision.reason = "changed"  # type: ignore[misc]

    def test_enum_strings_are_coerced(self) -> None:
        rule = PolicyRule("id", "deny", (ResourcePattern("tool", " X "),))  # type: ignore[arg-type]
        assert rule.action is PolicyAction.DENY
        assert rule.resources[0] == resource(ResourceKind.TOOL, "x")

    @pytest.mark.parametrize(
        ("kind", "raw", "canonical"),
        [
            (ResourceKind.TOOL, "  CAFÉ  ", "café"),
            (ResourceKind.TOOL, "CAFE\u0301", "café"),
            (ResourceKind.PATH, r"/srv//data/../data/./file", "/srv/data/file"),
            (ResourceKind.PATH, r"\srv\data\file", "/srv/data/file"),
            (ResourceKind.HOST, " BÜCHER.Example. ", "xn--bcher-kva.example"),
        ],
    )
    def test_resource_canonicalization(self, kind: ResourceKind, raw: str, canonical: str) -> None:
        assert resource(kind, raw).pattern == canonical

    def test_policy_request_canonicalizes_tool_and_rejects_pattern_resources(self) -> None:
        item = request(resource(ResourceKind.PATH, "/tmp/a"))
        assert item.tool_name == "read_file"
        with pytest.raises(ValueError, match="concrete"):
            request(resource(ResourceKind.HOST, "*.example.com"))

    @pytest.mark.parametrize("model", ["rule", "request"])
    def test_resource_elements_must_be_resource_patterns(self, model: str) -> None:
        invalid_resources = ("/tmp/not-a-resource-pattern",)
        with pytest.raises(TypeError, match="resources must contain only ResourcePattern"):
            if model == "rule":
                PolicyRule("invalid", PolicyAction.DENY, invalid_resources)  # type: ignore[arg-type]
            else:
                PolicyRequest(
                    "read_file",
                    invalid_resources,  # type: ignore[arg-type]
                    frozenset({RiskClass.READ}),
                )

    def test_rule_rejects_duplicate_canonical_resources(self) -> None:
        with pytest.raises(ValueError, match="duplicate canonical resource"):
            PolicyRule(
                "duplicate",
                PolicyAction.ALLOW,
                (
                    resource(ResourceKind.TOOL, "READ_FILE"),
                    resource(ResourceKind.TOOL, " read_file "),
                ),
            )

    @pytest.mark.parametrize("invalid", [0, 1, "true", None])
    def test_enabled_must_be_an_exact_bool(self, invalid: object) -> None:
        with pytest.raises(TypeError, match="enabled must be a bool"):
            PolicyRule("invalid-enabled", PolicyAction.ALLOW, enabled=invalid)  # type: ignore[arg-type]

    @pytest.mark.parametrize("invalid", [0, 1, "false", None])
    def test_legacy_requires_approval_must_be_an_exact_bool(self, invalid: object) -> None:
        with pytest.raises(TypeError, match="legacy_requires_approval must be a bool"):
            PolicyRequest(
                "read_file",
                (),
                frozenset({RiskClass.READ}),
                legacy_requires_approval=invalid,  # type: ignore[arg-type]
            )

    def test_description_allows_empty_but_rejects_non_strings_and_controls(self) -> None:
        assert PolicyRule("empty-description", PolicyAction.ALLOW, description="").description == ""
        with pytest.raises(TypeError, match="description must be a string"):
            PolicyRule("non-string", PolicyAction.ALLOW, description=7)  # type: ignore[arg-type]
        for invalid in ("line\nbreak", "tab\tcharacter", "zero\x00byte"):
            with pytest.raises(ValueError, match="control characters"):
                PolicyRule("control", PolicyAction.ALLOW, description=invalid)

    @pytest.mark.parametrize(
        ("kind", "pattern"),
        [
            (ResourceKind.TOOL, ""),
            (ResourceKind.TOOL, "foo*"),
            (ResourceKind.TOOL, "bad\nname"),
            (ResourceKind.PATH, "relative/path"),
            (ResourceKind.PATH, "/tmp/*"),
            (ResourceKind.PATH, "/tmp/**/nested"),
            (ResourceKind.HOST, "foo.*.com"),
            (ResourceKind.HOST, "https://example.com"),
            (ResourceKind.HOST, "user@example.com"),
            (ResourceKind.HOST, "example.com:443"),
            (ResourceKind.HOST, ".example.com"),
            (ResourceKind.HOST, "bad_host.example"),
            (ResourceKind.HOST, "127.1"),
            (ResourceKind.HOST, "2130706433"),
            (ResourceKind.HOST, "0177.0.0.1"),
        ],
    )
    def test_malformed_resources_are_rejected(self, kind: ResourceKind, pattern: str) -> None:
        with pytest.raises(ValueError):
            resource(kind, pattern)

    def test_invalid_rule_and_request_values_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="id"):
            PolicyRule(" ", PolicyAction.ALLOW)
        with pytest.raises(ValueError, match="tool"):
            PolicyRequest(" ", (), frozenset({RiskClass.READ}))

    @pytest.mark.parametrize(
        "alias",
        [
            "0x7f000001",
            "0X7F000001",
            "0x7f.0.0.1",
            "0X7F.0.0.1",
            "127.0x0.0.1",
            "127.0X0.0.1",
            "0x7f.1",
            "0X7F.01",
        ],
    )
    def test_hexadecimal_legacy_ipv4_aliases_are_rejected(self, alias: str) -> None:
        with pytest.raises(ValueError, match="noncanonical IPv4 numeric alias"):
            resource(ResourceKind.HOST, alias)

    def test_hosts_use_idna2008_uts46_and_canonical_ipv4(self) -> None:
        assert resource(ResourceKind.HOST, "faß.de").pattern == "xn--fa-hia.de"
        assert resource(ResourceKind.HOST, "127.0.0.1").pattern == "127.0.0.1"

    @pytest.mark.parametrize("hostname", ["x.example", "0xcorp.example", "0xface.example"])
    def test_non_numeric_hostnames_containing_x_are_accepted(self, hostname: str) -> None:
        assert resource(ResourceKind.HOST, hostname).pattern == hostname


@pytest.mark.unit
class TestRulePolicyEngine:
    def test_exact_rule_matches_and_reason_is_readable(self) -> None:
        engine = RulePolicyEngine(
            [
                PolicyRule(
                    "allow-read",
                    PolicyAction.ALLOW,
                    (resource(ResourceKind.TOOL, "read_file"),),
                    frozenset({RiskClass.READ}),
                    "read-only files",
                )
            ]
        )
        decision = engine.evaluate(request(resource(ResourceKind.TOOL, "READ_FILE")))
        assert decision.action is PolicyAction.ALLOW
        assert decision.matched_rule_id == "allow-read"
        assert decision.specificity == (1, len("read_file"), 1)
        assert "allow-read" in decision.reason
        assert "read-only files" in decision.reason

    def test_every_rule_resource_must_match_same_kind_request_resource(self) -> None:
        rule = PolicyRule(
            "two-resources",
            PolicyAction.DENY,
            (
                resource(ResourceKind.TOOL, "fetch"),
                resource(ResourceKind.HOST, "api.example.com"),
            ),
        )
        engine = RulePolicyEngine([rule])
        item = PolicyRequest(
            "fetch",
            (resource(ResourceKind.TOOL, "fetch"), resource(ResourceKind.HOST, "other.com")),
            frozenset({RiskClass.NETWORK}),
        )
        assert engine.evaluate(item).matched_rule_id is None

    def test_path_prefix_matches_descendants_but_not_siblings_or_prefix_itself(self) -> None:
        engine = RulePolicyEngine(
            [
                PolicyRule(
                    "private", PolicyAction.DENY, (resource(ResourceKind.PATH, "/srv/app/**"),)
                )
            ]
        )
        descendant = request(resource(ResourceKind.PATH, "/srv/app/secrets/key"))
        sibling = request(resource(ResourceKind.PATH, "/srv/application/secrets"))
        prefix = request(resource(ResourceKind.PATH, "/srv/app"))
        assert engine.evaluate(descendant).matched_rule_id == "private"
        assert engine.evaluate(sibling).matched_rule_id is None
        assert engine.evaluate(prefix).matched_rule_id is None

    def test_root_path_wildcard_matches_absolute_resources(self) -> None:
        engine = RulePolicyEngine(
            [PolicyRule("all-paths", PolicyAction.ASK, (resource(ResourceKind.PATH, "/**"),))]
        )
        assert (
            engine.evaluate(request(resource(ResourceKind.PATH, "/etc/hosts"))).action
            is PolicyAction.ASK
        )

    def test_host_wildcard_excludes_apex_and_deceptive_suffix(self) -> None:
        engine = RulePolicyEngine(
            [
                PolicyRule(
                    "subdomains",
                    PolicyAction.DENY,
                    (resource(ResourceKind.HOST, "*.example.com"),),
                )
            ]
        )
        subdomain = request(resource(ResourceKind.HOST, "api.example.com"))
        apex = request(resource(ResourceKind.HOST, "example.com"))
        deceptive = request(resource(ResourceKind.HOST, "example.com.attacker.test"))
        assert engine.evaluate(subdomain).matched_rule_id == "subdomains"
        assert engine.evaluate(apex).matched_rule_id is None
        assert engine.evaluate(deceptive).matched_rule_id is None

    def test_global_host_wildcard_matches_any_valid_host(self) -> None:
        engine = RulePolicyEngine(
            [PolicyRule("internet", PolicyAction.ASK, (resource(ResourceKind.HOST, "*"),))]
        )
        assert (
            engine.evaluate(request(resource(ResourceKind.HOST, "example.com"))).action
            is PolicyAction.ASK
        )

    def test_highest_specificity_wins_independent_of_order(self) -> None:
        broad = PolicyRule("broad", PolicyAction.DENY, (resource(ResourceKind.TOOL, "*"),))
        exact = PolicyRule("exact", PolicyAction.ALLOW, (resource(ResourceKind.TOOL, "read_file"),))
        item = request(resource(ResourceKind.TOOL, "read_file"))
        assert RulePolicyEngine([exact, broad]).evaluate(item).matched_rule_id == "exact"
        assert RulePolicyEngine([broad, exact]).evaluate(item).matched_rule_id == "exact"

    def test_risk_specific_rule_is_more_specific_and_requires_intersection(self) -> None:
        generic = PolicyRule("generic", PolicyAction.ALLOW)
        risky = PolicyRule("network", PolicyAction.ASK, risk_classes=frozenset({RiskClass.NETWORK}))
        engine = RulePolicyEngine([generic, risky])
        network = request(risks=frozenset({RiskClass.NETWORK}))
        read = request(risks=frozenset({RiskClass.READ}))
        assert engine.evaluate(network).matched_rule_id == "network"
        assert engine.evaluate(read).matched_rule_id == "generic"

    def test_equal_specificity_deny_wins_even_when_not_last(self) -> None:
        rules = [
            PolicyRule("deny", PolicyAction.DENY, (resource(ResourceKind.TOOL, "read_file"),)),
            PolicyRule(
                "later-allow", PolicyAction.ALLOW, (resource(ResourceKind.TOOL, "read_file"),)
            ),
        ]
        assert RulePolicyEngine(rules).evaluate(request()).matched_rule_id == "deny"

    def test_equal_specificity_uses_last_match_without_deny(self) -> None:
        rules = [PolicyRule("allow", PolicyAction.ALLOW), PolicyRule("ask", PolicyAction.ASK)]
        assert RulePolicyEngine(rules).evaluate(request()).matched_rule_id == "ask"

    def test_disabled_rule_is_ignored(self) -> None:
        engine = RulePolicyEngine([PolicyRule("off", PolicyAction.DENY, enabled=False)])
        decision = engine.evaluate(request())
        assert decision.action is PolicyAction.ALLOW
        assert decision.matched_rule_id is None
        assert "default" in decision.reason.lower()

    def test_legacy_requires_approval_falls_back_to_ask(self) -> None:
        decision = RulePolicyEngine([]).evaluate(request(legacy=True))
        assert decision.action is PolicyAction.ASK
        assert "legacy" in decision.reason.lower()

    def test_unknown_unclassified_request_is_denied(self) -> None:
        item = request(risks=frozenset())
        decision = RulePolicyEngine([], default_action=PolicyAction.ALLOW).evaluate(item)
        assert decision.action is PolicyAction.DENY
        assert "unclassified" in decision.reason.lower()

    def test_generic_allow_cannot_authorize_unclassified_request(self) -> None:
        decision = RulePolicyEngine([PolicyRule("generic", PolicyAction.ALLOW)]).evaluate(
            request(risks=frozenset())
        )
        assert decision.action is PolicyAction.DENY
        assert decision.matched_rule_id is None
        assert "unclassified" in decision.reason.lower()

    @pytest.mark.parametrize("action", [PolicyAction.ALLOW, PolicyAction.ASK])
    def test_allow_and_ask_risk_rules_must_cover_every_requested_risk(
        self, action: PolicyAction
    ) -> None:
        engine = RulePolicyEngine(
            [
                PolicyRule(
                    "read-only",
                    action,
                    risk_classes=frozenset({RiskClass.READ}),
                )
            ]
        )
        decision = engine.evaluate(request(risks=frozenset({RiskClass.READ, RiskClass.WRITE})))
        assert decision.action is PolicyAction.DENY
        assert decision.matched_rule_id is None

    @pytest.mark.parametrize("action", [PolicyAction.ALLOW, PolicyAction.ASK])
    def test_allow_and_ask_risk_rules_can_cover_every_requested_risk(
        self, action: PolicyAction
    ) -> None:
        engine = RulePolicyEngine(
            [
                PolicyRule(
                    "full-cover",
                    action,
                    risk_classes=frozenset({RiskClass.READ, RiskClass.WRITE}),
                )
            ]
        )
        decision = engine.evaluate(request(risks=frozenset({RiskClass.READ, RiskClass.WRITE})))
        assert decision.action is action
        assert decision.matched_rule_id == "full-cover"

    def test_deny_risk_rule_matches_any_denied_requested_risk_and_wins_tie(self) -> None:
        risks = frozenset({RiskClass.READ, RiskClass.WRITE})
        rules = [
            PolicyRule("deny-write", PolicyAction.DENY, risk_classes=frozenset({RiskClass.WRITE})),
            PolicyRule("allow-full", PolicyAction.ALLOW, risk_classes=risks),
        ]
        decision = RulePolicyEngine(rules).evaluate(request(risks=risks))
        assert decision.action is PolicyAction.DENY
        assert decision.matched_rule_id == "deny-write"

    @pytest.mark.parametrize(
        "risk",
        [
            RiskClass.WRITE,
            RiskClass.EXECUTE,
            RiskClass.NETWORK,
            RiskClass.SECRET,
            RiskClass.EXTERNAL_SIDE_EFFECT,
        ],
    )
    def test_unmatched_side_effecting_request_is_denied(self, risk: RiskClass) -> None:
        item = request(risks=frozenset({risk}))
        decision = RulePolicyEngine([], default_action=PolicyAction.ALLOW).evaluate(item)
        assert decision.action is PolicyAction.DENY
        assert "side-effecting" in decision.reason.lower()

    def test_explicitly_classified_safe_request_uses_configured_default(self) -> None:
        item = request(risks=frozenset({RiskClass.READ}))
        decision = RulePolicyEngine([], default_action=PolicyAction.ASK).evaluate(item)
        assert decision.action is PolicyAction.ASK
        assert decision.risk_classes == frozenset({RiskClass.READ})


@pytest.mark.unit
class TestArgumentsHash:
    def test_hash_is_canonical_across_mapping_order(self) -> None:
        left = {"b": [True, None, {"z": "é"}], "a": 1}
        right = {"a": 1, "b": [True, None, {"z": "é"}]}
        assert arguments_hash(left) == arguments_hash(right)
        assert canonical_arguments_hash(left) == arguments_hash(left)
        assert len(arguments_hash(left)) == 64

    def test_hash_distinguishes_json_types(self) -> None:
        assert arguments_hash({"value": 1}) != arguments_hash({"value": "1"})

    def test_hash_preserves_exact_unicode_string_and_key_semantics(self) -> None:
        assert arguments_hash({"value": "é"}) != arguments_hash({"value": "e\u0301"})
        assert arguments_hash({"é": "value"}) != arguments_hash({"e\u0301": "value"})

        distinct_keys = {"é": 1, "e\u0301": 2}
        assert len(arguments_hash(distinct_keys)) == 64

    def test_hash_rejects_cycles(self) -> None:
        cyclic: list[object] = []
        cyclic.append(cyclic)
        with pytest.raises(ValueError, match="cycles"):
            arguments_hash(cyclic)

    @pytest.mark.parametrize(
        "invalid",
        [
            {"x": float("nan")},
            {"x": float("inf")},
            {"x": float("-inf")},
            {"x": object()},
            {1: "non-string key"},
            {"x": (1, 2)},
        ],
    )
    def test_invalid_or_unsupported_values_are_rejected(self, invalid: object) -> None:
        with pytest.raises((TypeError, ValueError)):
            arguments_hash(invalid)
