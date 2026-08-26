"""Security probe tests — RED-GREEN pattern.

These tests prove security vulnerabilities exist (RED) and that our
fixes prevent them (GREEN). This is the crown jewel of the test suite.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.agents.protocols import AuditLog, PermissionChecker
from app.security.audit_logger import StructuredAuditLogger
from app.security.permission_manager import SecurePermissionManager
from app.security.persistence_redactor import PersistenceRedactor


@pytest.fixture
def workspace() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "workspace"
        ws.mkdir()
        (ws / "test.txt").write_text("safe content")
        yield ws


@pytest.fixture
def perms(workspace: Path) -> SecurePermissionManager:
    return SecurePermissionManager(base_dir=workspace)


class TestPermissionManagerProtocol:
    """Protocol compliance."""

    @pytest.mark.unit
    def test_satisfies_protocol(self, perms: SecurePermissionManager) -> None:
        assert isinstance(perms, PermissionChecker)


class TestPathTraversalPrevention:
    """RED-GREEN: path traversal attacks must be blocked."""

    @pytest.mark.security
    @pytest.mark.asyncio
    async def test_blocks_parent_directory_traversal(
        self, perms: SecurePermissionManager, workspace: Path
    ) -> None:
        """../../etc/passwd must be DENIED."""
        evil_path = str(workspace / "../../etc/passwd")
        allowed = await perms.check("agent", evil_path, "read_file", path=evil_path)
        assert allowed is False

    @pytest.mark.security
    @pytest.mark.asyncio
    async def test_blocks_absolute_escape(self, perms: SecurePermissionManager) -> None:
        """/etc/passwd must be DENIED."""
        allowed = await perms.check("agent", "/etc/passwd", "read_file", path="/etc/passwd")
        assert allowed is False

    @pytest.mark.security
    @pytest.mark.asyncio
    async def test_blocks_sibling_prefix_attack(
        self, perms: SecurePermissionManager, workspace: Path
    ) -> None:
        """workspace-evil must be DENIED (the Day 3 bug).

        Without the trailing '/' fix, '/tmp/workspace-evil' matches '/tmp/workspace'.
        """
        evil_path = str(workspace) + "-evil/secret.txt"
        allowed = await perms.check("agent", evil_path, "read_file", path=evil_path)
        assert allowed is False

    @pytest.mark.security
    @pytest.mark.asyncio
    async def test_allows_valid_path(self, perms: SecurePermissionManager, workspace: Path) -> None:
        """Files inside workspace must be ALLOWED."""
        valid_path = str(workspace / "test.txt")
        allowed = await perms.check("agent", valid_path, "read_file", path=valid_path)
        assert allowed is True

    @pytest.mark.security
    @pytest.mark.asyncio
    async def test_allows_workspace_root(
        self, perms: SecurePermissionManager, workspace: Path
    ) -> None:
        """The workspace directory itself must be ALLOWED."""
        allowed = await perms.check("agent", str(workspace), "list_directory", path=str(workspace))
        assert allowed is True


class TestActionAllowlist:
    """Only whitelisted actions are permitted."""

    @pytest.mark.security
    @pytest.mark.asyncio
    async def test_blocks_unknown_action(self, perms: SecurePermissionManager) -> None:
        allowed = await perms.check("agent", "anything", "delete_database")
        assert allowed is False

    @pytest.mark.security
    @pytest.mark.asyncio
    async def test_allows_known_action(self, perms: SecurePermissionManager) -> None:
        allowed = await perms.check("agent", "anything", "search")
        assert allowed is True


class TestSymlinkResolution:
    """Symlinks that point outside workspace must be blocked."""

    @pytest.mark.security
    @pytest.mark.asyncio
    async def test_blocks_symlink_escape(
        self, perms: SecurePermissionManager, workspace: Path
    ) -> None:
        """Symlink inside workspace pointing to /etc must be DENIED."""
        symlink = workspace / "sneaky_link"
        try:
            symlink.symlink_to("/etc")
            allowed = await perms.check(
                "agent",
                str(symlink / "passwd"),
                "read_file",
                path=str(symlink / "passwd"),
            )
            assert allowed is False
        finally:
            if symlink.exists():
                symlink.unlink()


class TestAuditLoggerProtocol:
    """Audit logger protocol compliance and functionality."""

    @pytest.mark.unit
    def test_satisfies_protocol(self) -> None:
        audit = StructuredAuditLogger(PersistenceRedactor())
        assert isinstance(audit, AuditLog)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_log_and_retrieve(self) -> None:
        audit = StructuredAuditLogger(PersistenceRedactor())
        correlation_id = "00000000-0000-0000-0000-000000000001"
        await audit.log(agent_id="a1", action="test", resource="r1", correlation_id=correlation_id)

        entries = await audit.get_recent(limit=10)
        assert len(entries) == 1
        assert entries[0]["agent_id"] == "a1"
        assert entries[0]["correlation_id"] == correlation_id

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_search_by_correlation_id(self) -> None:
        audit = StructuredAuditLogger(PersistenceRedactor())
        target = "00000000-0000-0000-0000-000000000001"
        other = "00000000-0000-0000-0000-000000000002"
        await audit.log(agent_id="a1", action="x", resource="r1", correlation_id=target)
        await audit.log(agent_id="a1", action="y", resource="r2", correlation_id=other)

        results = await audit.search(correlation_id=target)
        assert len(results) == 1
        assert results[0]["action"] == "x"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_search_by_security_level(self) -> None:
        audit = StructuredAuditLogger(PersistenceRedactor())
        await audit.log(agent_id="a1", action="ok", resource="r1", security_level="info")
        await audit.log(agent_id="a1", action="bad", resource="r2", security_level="warning")

        warnings = await audit.search(security_level="warning")
        assert len(warnings) == 1
        assert warnings[0]["action"] == "bad"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_count_by_action(self) -> None:
        audit = StructuredAuditLogger(PersistenceRedactor())
        await audit.log(agent_id="a1", action="read", resource="r1")
        await audit.log(agent_id="a1", action="read", resource="r2")
        await audit.log(agent_id="a1", action="write", resource="r3")

        counts = await audit.count_by_action()
        assert counts["read"] == 2
        assert counts["write"] == 1
