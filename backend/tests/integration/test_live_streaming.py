"""Live-provider integration tests for SSE streaming bugs.

These tests hit the running Archon stack with real LLM calls. They cost money
and are non-deterministic (the model decides which tools to call).

Run explicitly:
    ARCHON_LIVE_TESTS=1 uv run pytest tests/integration/test_live_streaming.py -v

Prerequisites:
    - Stack running: ./scripts/local-stack.sh start --live-provider
    - Admin user registered
"""

from __future__ import annotations

import json
import os

import pytest
import requests

LIVE = os.environ.get("ARCHON_LIVE_TESTS", "") == "1"
BASE_URL = os.environ.get("ARCHON_BASE_URL", "http://127.0.0.1:80")

pytestmark = [
    pytest.mark.skipif(not LIVE, reason="Set ARCHON_LIVE_TESTS=1 to run live tests"),
    pytest.mark.live,
]


# ── Helpers ────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def session() -> requests.Session:
    """Authenticated requests session against the live stack."""
    s = requests.Session()
    r = s.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": "admin", "password": "StrongPass123!"},
    )
    if r.status_code != 200:
        r = s.post(
            f"{BASE_URL}/api/auth/register",
            json={"username": "admin", "password": "StrongPass123!"},
        )
        r.raise_for_status()
    token = r.json()["access_token"]
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def _create_conversation(session: requests.Session) -> str:
    r = session.post(f"{BASE_URL}/api/conversations", json={})
    r.raise_for_status()
    return r.json()["id"]


def _stream_chat(session: requests.Session, conv_id: str, message: str) -> str:
    """Send a chat message and return the raw SSE text."""
    r = session.post(
        f"{BASE_URL}/api/chat/stream",
        json={"message": message, "conversation_id": conv_id},
        stream=True,
        timeout=300,
    )
    r.raise_for_status()
    return r.text


def _extract_sse_data(text: str, event_name: str) -> list[str]:
    results = []
    marker = f"event: {event_name}\ndata: "
    for part in text.split(marker)[1:]:
        results.append(part.split("\n\n", 1)[0])
    return results


def _count_progress_per_tool_call(text: str) -> dict[str, int]:
    """Count thinking events per tool_call_id."""
    counts: dict[str, int] = {}
    for payload_str in _extract_sse_data(text, "thinking"):
        try:
            payload = json.loads(payload_str)
            if isinstance(payload, dict) and "tool_call_id" in payload:
                tcid = payload["tool_call_id"]
                counts[tcid] = counts.get(tcid, 0) + 1
        except (json.JSONDecodeError, TypeError):
            continue
    return counts


def _done_payload(text: str) -> dict:
    payloads = _extract_sse_data(text, "done")
    assert payloads, "No done event in SSE stream"
    return json.loads(payloads[0])


# ── Tests ──────────────────────────────────────────────────────────


def test_live_web_search_does_not_spam_progress(session: requests.Session) -> None:
    """A prompt that triggers web_search should not produce more than 2
    progress thinking events per tool_call_id in the SSE stream."""
    conv_id = _create_conversation(session)
    sse_text = _stream_chat(
        session,
        conv_id,
        "Search the web for the current population of Belgium. Give me just the number.",
    )

    counts = _count_progress_per_tool_call(sse_text)
    for tcid, count in counts.items():
        assert count <= 2, (
            f"tool_call_id {tcid} had {count} progress thinking events (expected <= 2)"
        )


def test_live_multi_tool_renders_final_answer(session: requests.Session) -> None:
    """A prompt that uses multiple tools must still produce token events
    with a non-empty final answer in the SSE stream."""
    conv_id = _create_conversation(session)
    sse_text = _stream_chat(
        session,
        conv_id,
        "What is 2+2? Also search the web for today's weather in Brussels. "
        "Give me both answers in your response.",
    )

    token_payloads = _extract_sse_data(sse_text, "token")
    combined = "".join(token_payloads)
    assert len(combined) > 10, (
        f"Expected substantial token content, got {len(combined)} chars: {combined[:200]!r}"
    )
    done = _done_payload(sse_text)
    assert done["stop_reason"] in ("completed", "iteration_budget_exhausted")


def test_live_complex_multi_step_with_artifacts(session: requests.Session) -> None:
    """A complex prompt that requires multiple web searches, calculator, and
    code/artifact generation must render content and not silently drop the
    response regardless of how many tool iterations are needed."""
    conv_id = _create_conversation(session)
    sse_text = _stream_chat(
        session,
        conv_id,
        "Search the web for the top 5 most valuable companies in the world in 2026 "
        "and their market cap. Calculate the percentage growth vs 2025 for each. "
        "Present the results in a clean HTML table with company name, 2025 cap, "
        "2026 cap, and growth percentage.",
    )

    # Must have token content — either the real answer or a budget-exhaustion message
    token_payloads = _extract_sse_data(sse_text, "token")
    combined = "".join(token_payloads)
    assert len(combined) > 20, (
        f"Response content too short or empty ({len(combined)} chars). "
        f"The user sees nothing. Preview: {combined[:300]!r}"
    )

    # Must have a done event
    done = _done_payload(sse_text)
    # The model may choose to answer directly or use tools — both are valid.
    # We only assert it ran and produced output.
    assert done["iterations"] >= 1, "Expected at least 1 iteration"

    # Progress events must be deduplicated
    counts = _count_progress_per_tool_call(sse_text)
    for tcid, count in counts.items():
        assert count <= 2, (
            f"tool_call_id {tcid} had {count} progress thinking events (expected <= 2)"
        )


def test_live_heavy_research_renders_something(session: requests.Session) -> None:
    """A research-intensive prompt that will likely exhaust budget must still
    render visible content — either the answer or a clear budget message.
    This is the exact class of prompt that was broken before the fix."""
    conv_id = _create_conversation(session)
    sse_text = _stream_chat(
        session,
        conv_id,
        "Busca las 5 empresas más valiosas del mundo en 2026, calcula el "
        "crecimiento porcentual vs 2025, y crea una página HTML interactiva "
        "con una tabla estilizada que muestre los resultados.",
    )

    token_payloads = _extract_sse_data(sse_text, "token")
    combined = "".join(token_payloads)

    # The absolute requirement: the user must see SOMETHING
    assert len(combined) > 0, (
        "CRITICAL: No token content at all — user sees 'Completed!' with empty response. "
        f"Stop reason: {_done_payload(sse_text).get('stop_reason', 'unknown')}"
    )

    done = _done_payload(sse_text)
    # Log for diagnosis — not a failure condition
    print(
        f"\n  stop_reason={done['stop_reason']}, "
        f"iterations={done['iterations']}, "
        f"tools={done['tools_used']}, "
        f"tokens={done.get('tokens_used', '?')}, "
        f"content_length={len(combined)}"
    )


def test_live_code_generation_prompt(session: requests.Session) -> None:
    """A prompt that asks for code generation plus web research should produce
    visible output with tool calls and substantial content."""
    conv_id = _create_conversation(session)
    sse_text = _stream_chat(
        session,
        conv_id,
        "Search the web for the current Bitcoin price. Then write a Python "
        "function that converts USD to BTC using that price. Show the code "
        "and explain how it works.",
    )

    token_payloads = _extract_sse_data(sse_text, "token")
    combined = "".join(token_payloads)
    assert len(combined) > 50, (
        f"Expected substantial code + explanation, got {len(combined)} chars: {combined[:200]!r}"
    )

    # Should have used web_search
    tool_calls = _extract_sse_data(sse_text, "tool_call")
    tool_names = []
    for tc_str in tool_calls:
        try:
            tc = json.loads(tc_str)
            tool_names.append(tc.get("tool") or tc.get("name", ""))
        except (json.JSONDecodeError, TypeError):
            continue
    assert any("web_search" in n for n in tool_names), (
        f"Expected web_search tool call, got: {tool_names}"
    )
