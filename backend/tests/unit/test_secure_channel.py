"""Tests for secure inter-agent communication channel."""

from __future__ import annotations

import time

import pytest

from app.agents.secure_channel import SecureChannel


class TestSecureChannel:
    """Tests for HMAC-SHA256 message signing/verification."""

    @pytest.mark.unit
    def test_sign_and_verify(self) -> None:
        ch = SecureChannel(secret="test-secret")
        msg = ch.sign_message("planner", "retriever", "find docs about X")
        assert ch.verify_message(msg) is True

    @pytest.mark.unit
    def test_tampered_content_fails(self) -> None:
        ch = SecureChannel(secret="test-secret")
        msg = ch.sign_message("planner", "retriever", "find docs about X")
        msg.content = "tampered content"
        assert ch.verify_message(msg) is False

    @pytest.mark.unit
    def test_wrong_secret_fails(self) -> None:
        ch1 = SecureChannel(secret="secret-a")
        ch2 = SecureChannel(secret="secret-b")
        msg = ch1.sign_message("a", "b", "hello")
        assert ch2.verify_message(msg) is False

    @pytest.mark.unit
    def test_expired_message_fails(self) -> None:
        ch = SecureChannel(secret="s", max_age_seconds=0.0)
        msg = ch.sign_message("a", "b", "c")
        # Message is immediately expired since max_age is 0
        time.sleep(0.01)
        assert ch.verify_message(msg) is False

    @pytest.mark.unit
    def test_signed_message_to_dict(self) -> None:
        ch = SecureChannel(secret="s")
        msg = ch.sign_message("planner", "retriever", "payload")
        d = msg.to_dict()
        assert d["from_agent"] == "planner"
        assert d["to_agent"] == "retriever"
        assert d["content"] == "payload"
        assert "signature" in d
        assert "timestamp" in d
