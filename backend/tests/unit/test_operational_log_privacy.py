"""Source-level privacy probes for user-controlled operational log fields."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
import structlog
from structlog.testing import capture_logs

from app.routes import conversations
from app.tools import terminal, web_search

PII = "private.user@example.com 123-45-6789 4111-1111-1111-1111 202-555-0147"


def _prefix(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_terminal_logs_only_command_length_and_hash(monkeypatch) -> None:
    command = f"printf %s {PII!r}"
    with capture_logs() as logs:
        monkeypatch.setattr(terminal, "logger", structlog.get_logger())
        result = await terminal.terminal_tool(command)

    assert result["exit_code"] == 0
    assert PII not in repr(logs)
    assert logs[-1]["command_length"] == len(command)
    assert logs[-1]["command_sha256"] == _prefix(command)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_web_search_logs_safe_query_and_exception_metadata(monkeypatch) -> None:
    async def fail(*args, **kwargs):
        del args, kwargs
        raise ValueError(f"provider echoed {PII}")

    monkeypatch.setattr(web_search, "_searxng_search", fail)
    monkeypatch.setattr(web_search, "_duckduckgo_search", fail)
    monkeypatch.delenv("ARCHON_BRAVE_API_KEY", raising=False)
    with capture_logs() as logs:
        monkeypatch.setattr(web_search, "logger", structlog.get_logger())
        result = await web_search.web_search_tool(PII)

    assert result["total"] == 0
    assert PII not in repr(logs)
    assert "provider echoed" not in repr(logs)
    assert all(log["query_length"] == len(PII) for log in logs)
    assert all(log["query_sha256"] == _prefix(PII) for log in logs)
    assert logs[0]["error_type"] == "ValueError"
    assert logs[0]["error_reason"] == "provider_request_failed"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_conversation_title_log_contains_only_safe_metadata(monkeypatch) -> None:
    class Repository:
        async def create(self, conversation_id, title, user_id):
            del user_id
            return {
                "id": conversation_id,
                "title": title,
                "created_at": "2026-01-01T00:00:00Z",
                "message_count": 0,
            }

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(conversations=Repository()))
    )
    with capture_logs() as logs:
        monkeypatch.setattr(conversations, "logger", structlog.get_logger())
        await conversations.create_conversation(
            conversations.ConversationCreate(title=PII), request, {"user_id": "owner"}
        )

    assert PII not in repr(logs)
    assert logs[0]["title_length"] == len(PII)
    assert logs[0]["title_sha256"] == _prefix(PII)
