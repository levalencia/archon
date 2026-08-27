"""Tests for streaming tool progress and background tasks."""

from __future__ import annotations

import asyncio

import pytest

from app.runtime.engine import AgentRuntime, RuntimeBudget
from app.runtime.events import AgentEventKind, RecordingEventSink
from app.runtime.models import Message, ModelResponse, Role, ToolCall
from app.services.task_queue import TaskQueue

# ---------- TASK 2: Streaming tool progress ----------


class _FakeProvider:
    """Fake model provider that requests one tool call, then returns text."""

    def __init__(self, tool_output: dict) -> None:
        self._call_count = 0
        self._tool_output = tool_output

    async def complete(
        self,
        messages,
        tools=(),
        *,
        max_tokens=4096,
        response_contract=None,
        response_format=None,
    ):
        del response_contract, response_format
        self._call_count += 1
        if self._call_count == 1:
            # First call: request a tool
            return ModelResponse(
                content="",
                tool_calls=(ToolCall(id="tc1", name="big_tool", arguments={"x": 1}),),
            )
        # Second call: produce final text
        return ModelResponse(content="done")

    def definitions(self):
        return ()


class _FakeToolExecutor:
    def __init__(self, output: dict):
        self._output = output

    async def execute(self, call):
        return self._output

    def definitions(self):
        return ()

    def tool_requires_approval(self, name):
        return False


class TestToolProgress:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tool_progress_emitted_for_large_result(self) -> None:
        """TOOL_PROGRESS events should be emitted when tool result > 500 chars."""
        large_output = {"data": "x" * 600}
        sink = RecordingEventSink()
        runtime = AgentRuntime(
            _FakeProvider(large_output),
            _FakeToolExecutor(large_output),
            events=sink,
            budget=RuntimeBudget(max_iterations=3, max_tool_calls=3, max_seconds=10),
        )
        await runtime.run([Message(Role.USER, "test")])
        progress_events = [e for e in sink.events if e.kind == AgentEventKind.TOOL_PROGRESS]
        assert len(progress_events) >= 1
        # Check chunk data is present
        assert "chunk" in progress_events[0].data
        assert "offset" in progress_events[0].data

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_no_tool_progress_for_small_result(self) -> None:
        """No TOOL_PROGRESS events for results <= 500 chars."""
        small_output = {"ok": True}
        sink = RecordingEventSink()
        runtime = AgentRuntime(
            _FakeProvider(small_output),
            _FakeToolExecutor(small_output),
            events=sink,
            budget=RuntimeBudget(max_iterations=3, max_tool_calls=3, max_seconds=10),
        )
        await runtime.run([Message(Role.USER, "test")])
        progress_events = [e for e in sink.events if e.kind == AgentEventKind.TOOL_PROGRESS]
        assert len(progress_events) == 0


# ---------- TASK 3: Background tasks ----------


class TestTaskQueue:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_submit_and_complete(self) -> None:
        queue = TaskQueue()

        async def my_job() -> str:
            return "done"

        task_id = await queue.submit_task(my_job)
        assert task_id
        # Wait briefly for task to complete
        await asyncio.sleep(0.1)
        status = queue.get_status(task_id)
        assert status is not None
        assert status["status"] == "completed"
        assert status["result"] == "done"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_failed_task(self) -> None:
        queue = TaskQueue()

        async def failing_job() -> None:
            raise ValueError("boom")

        task_id = await queue.submit_task(failing_job)
        await asyncio.sleep(0.1)
        status = queue.get_status(task_id)
        assert status is not None
        assert status["status"] == "failed"
        assert "boom" in (status["error"] or "")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_tasks(self) -> None:
        queue = TaskQueue()

        async def noop() -> None:
            pass

        await queue.submit_task(noop)
        await queue.submit_task(noop)
        await asyncio.sleep(0.1)
        tasks = queue.list_tasks()
        assert len(tasks) == 2

    @pytest.mark.unit
    def test_get_status_not_found(self) -> None:
        queue = TaskQueue()
        assert queue.get_status("nonexistent") is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cancel_task(self) -> None:
        queue = TaskQueue()

        async def long_task() -> None:
            await asyncio.sleep(100)

        task_id = await queue.submit_task(long_task)
        await asyncio.sleep(0.05)
        assert queue.cancel(task_id) is True
        status = queue.get_status(task_id)
        assert status is not None
        assert status["status"] == "failed"
        assert "Cancelled" in (status["error"] or "")
