"""Tests for multi-agent authentication tokens."""

from __future__ import annotations

import time

import pytest

from app.agents.agent_auth import (
    check_permission,
    create_agent_token,
    verify_agent_token,
)


class TestAgentAuth:
    """Tests for agent token creation and verification."""

    @pytest.mark.unit
    def test_create_token_default_permissions(self) -> None:
        token = create_agent_token("retriever", "information_retrieval")
        assert token.agent_name == "retriever"
        assert "search" in token.permissions
        assert "retrieve" in token.permissions
        assert verify_agent_token(token) is True

    @pytest.mark.unit
    def test_create_token_custom_permissions(self) -> None:
        token = create_agent_token("custom", "custom_role", permissions=["read", "write"])
        assert token.permissions == ["read", "write"]

    @pytest.mark.unit
    def test_expired_token_fails(self) -> None:
        token = create_agent_token("a", "b", ttl_seconds=0.0)
        time.sleep(0.01)
        assert verify_agent_token(token) is False

    @pytest.mark.unit
    def test_check_permission_valid(self) -> None:
        token = create_agent_token("planner", "query_decomposition")
        assert check_permission(token, "plan") is True
        assert check_permission(token, "delete") is False

    @pytest.mark.unit
    def test_check_permission_expired(self) -> None:
        token = create_agent_token("a", "b", permissions=["do"], ttl_seconds=0.0)
        time.sleep(0.01)
        assert check_permission(token, "do") is False

    @pytest.mark.unit
    def test_token_to_dict(self) -> None:
        token = create_agent_token("validator", "quality_validation")
        d = token.to_dict()
        assert d["agent_name"] == "validator"
        assert "evaluate" in d["permissions"]
        assert d["expires_at"] > d["issued_at"]
