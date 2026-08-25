"""Tests for the terminal/shell tool."""

from __future__ import annotations

import pytest

from app.tools.terminal import is_command_blocked, terminal_tool


class TestCommandBlocklist:
    @pytest.mark.unit
    def test_rm_rf_blocked(self) -> None:
        assert is_command_blocked("rm -rf /") is not None
        assert is_command_blocked("rm -fr /tmp") is not None

    @pytest.mark.unit
    def test_sudo_blocked(self) -> None:
        assert is_command_blocked("sudo apt install foo") is not None

    @pytest.mark.unit
    def test_safe_command_allowed(self) -> None:
        assert is_command_blocked("echo hello") is None
        assert is_command_blocked("ls -la") is None
        assert is_command_blocked("cat /etc/hostname") is None

    @pytest.mark.unit
    def test_mkfs_blocked(self) -> None:
        assert is_command_blocked("mkfs.ext4 /dev/sda1") is not None

    @pytest.mark.unit
    def test_shutdown_blocked(self) -> None:
        assert is_command_blocked("shutdown -h now") is not None
        assert is_command_blocked("reboot") is not None


class TestTerminalTool:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_echo_command(self) -> None:
        result = await terminal_tool("echo hello world")
        assert result["exit_code"] == 0
        assert "hello world" in result["stdout"]
        assert result["timed_out"] is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_blocked_command_returns_error(self) -> None:
        result = await terminal_tool("sudo rm -rf /")
        assert result["exit_code"] == 1
        assert "Blocked" in result["stderr"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_nonexistent_command(self) -> None:
        result = await terminal_tool("nonexistent_command_xyz_12345")
        assert result["exit_code"] != 0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_timeout_clamped(self) -> None:
        # Timeout should be clamped to 1-120
        result = await terminal_tool("echo ok", timeout=0)
        assert result["exit_code"] == 0  # still runs, timeout clamped to 1

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stderr_captured(self) -> None:
        result = await terminal_tool("ls /nonexistent_path_xyz")
        assert result["exit_code"] != 0
        assert result["stderr"]  # Should have error output
