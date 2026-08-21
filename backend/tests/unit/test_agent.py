"""Tests for ProductionAgent ReAct loop."""

from __future__ import annotations

import json

import pytest

from app.agents.agent import AgentResult, ProductionAgent
from app.agents.mock_llm import MockLLM


class SimpleMemory:
    """Minimal in-memory store for testing."""

    def __init__(self) -> None:
        self._store: dict[str, list[dict[str, str]]] = {}

    async def store(self, conversation_id: str, role: str, content: str) -> None:
        self._store.setdefault(conversation_id, []).append({"role": role, "content": content})

    async def retrieve(self, conversation_id: str, limit: int = 50) -> list[dict[str, str]]:
        return self._store.get(conversation_id, [])[-limit:]


class SimpleTools:
    """Minimal tool executor for testing."""

    def __init__(self) -> None:
        self._tools: dict[str, dict] = {}

    def register(self, name: str, handler: object, description: str = "") -> None:
        self._tools[name] = {"handler": handler, "description": description}

    async def execute(self, tool_name: str, parameters: dict) -> dict:
        if tool_name not in self._tools:
            raise ValueError(f"Unknown tool: {tool_name}")
        handler = self._tools[tool_name]["handler"]
        if callable(handler):
            return handler(**parameters)  # type: ignore[no-any-return]
        return {"result": str(handler)}

    def list_tools(self) -> list[dict]:
        return [
            {"name": name, "description": info["description"]} for name, info in self._tools.items()
        ]


class SimpleAudit:
    """Minimal audit logger for testing."""

    def __init__(self) -> None:
        self.entries: list[dict] = []

    async def log(
        self,
        agent_id: str,
        action: str,
        resource: str,
        parameters: dict | None = None,
        result: str = "success",
        correlation_id: str | None = None,
        security_level: str = "info",
    ) -> None:
        self.entries.append(
            {
                "agent_id": agent_id,
                "action": action,
                "resource": resource,
                "parameters": parameters,
                "result": result,
                "correlation_id": correlation_id,
                "security_level": security_level,
            }
        )


class TestAgentDirectResponse:
    """Agent returns a direct response (no tool calls)."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_simple_response(self) -> None:
        llm = MockLLM(responses=["The answer is 42."])
        agent = ProductionAgent(llm=llm)

        result = await agent.run("What is the meaning of life?")

        assert isinstance(result, AgentResult)
        assert result.response == "The answer is 42."
        assert result.iterations == 1
        assert len(result.tool_calls) == 0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_result_has_correlation_id(self) -> None:
        llm = MockLLM(responses=["Hello!"])
        agent = ProductionAgent(llm=llm)

        result = await agent.run("Hi")

        assert len(result.correlation_id) == 36  # UUID

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_result_has_conversation_id(self) -> None:
        llm = MockLLM(responses=["Hello!"])
        agent = ProductionAgent(llm=llm)

        result = await agent.run("Hi", conversation_id="conv-123")

        assert result.conversation_id == "conv-123"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_auto_generates_conversation_id(self) -> None:
        llm = MockLLM(responses=["Hello!"])
        agent = ProductionAgent(llm=llm)

        result = await agent.run("Hi")

        assert len(result.conversation_id) == 36  # UUID


class TestAgentToolCalling:
    """Agent calls tools via the ReAct loop."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_single_tool_call(self) -> None:
        """LLM requests a tool, gets result, then gives final answer."""
        tool_call = json.dumps(
            {"tool_call": {"name": "search", "parameters": {"query": "weather"}}}
        )
        llm = MockLLM(responses=[tool_call, "The weather is sunny."])

        tools = SimpleTools()
        tools.register("search", lambda query: {"result": "Sunny, 25C"}, "Search the web")

        agent = ProductionAgent(llm=llm, tools=tools)
        result = await agent.run("What is the weather?")

        assert result.response == "The weather is sunny."
        assert result.iterations == 2
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["tool"] == "search"
        assert result.tool_calls[0]["status"] == "success"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_multiple_tool_calls(self) -> None:
        """LLM calls two tools before answering."""
        call1 = json.dumps({"tool_call": {"name": "search", "parameters": {"query": "population"}}})
        call2 = json.dumps(
            {"tool_call": {"name": "calculate", "parameters": {"expression": "1+1"}}}
        )
        llm = MockLLM(responses=[call1, call2, "The answer is 2."])

        tools = SimpleTools()
        tools.register("search", lambda query: {"result": "8 billion"}, "Search")
        tools.register("calculate", lambda expression: {"result": "2"}, "Calculate")

        agent = ProductionAgent(llm=llm, tools=tools)
        result = await agent.run("How many people plus one?")

        assert result.iterations == 3
        assert len(result.tool_calls) == 2

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self) -> None:
        """LLM requests a tool that does not exist."""
        tool_call = json.dumps({"tool_call": {"name": "nonexistent", "parameters": {}}})
        llm = MockLLM(responses=[tool_call, "I could not find that tool."])

        tools = SimpleTools()
        agent = ProductionAgent(llm=llm, tools=tools)
        result = await agent.run("Use the nonexistent tool")

        assert result.tool_calls[0]["status"] == "error"


class TestAgentSafetyControls:
    """Agent safety: max iterations, token budget."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_max_iterations_stops_loop(self) -> None:
        """Agent stops after max_iterations even if LLM keeps requesting tools."""
        tool_call = json.dumps({"tool_call": {"name": "search", "parameters": {"query": "loop"}}})
        # LLM always returns tool calls, never a final answer
        llm = MockLLM(responses=[tool_call] * 10)

        tools = SimpleTools()
        tools.register("search", lambda query: {"result": "data"}, "Search")

        agent = ProductionAgent(llm=llm, tools=tools, max_iterations=3)
        result = await agent.run("Keep searching forever")

        assert result.iterations == 3
        assert "maximum" in result.response.lower()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_custom_max_iterations(self) -> None:
        llm = MockLLM(responses=["Done."])
        agent = ProductionAgent(llm=llm, max_iterations=10)

        assert agent.max_iterations == 10


class TestAgentMemory:
    """Agent stores conversations in memory."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stores_user_and_assistant_messages(self) -> None:
        llm = MockLLM(responses=["Hello back!"])
        memory = SimpleMemory()
        agent = ProductionAgent(llm=llm, memory=memory)

        result = await agent.run("Hello!", conversation_id="conv-1")

        history = await memory.retrieve("conv-1")
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "Hello!"}
        assert history[1] == {"role": "assistant", "content": "Hello back!"}

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_retrieves_previous_context(self) -> None:
        """Second message includes history from first message."""
        llm = MockLLM(responses=["First response", "Second response"])
        memory = SimpleMemory()
        agent = ProductionAgent(llm=llm, memory=memory)

        await agent.run("First message", conversation_id="conv-1")
        await agent.run("Second message", conversation_id="conv-1")

        # LLM should have received context including first exchange
        second_call = llm.call_history[1]
        messages = second_call["messages"]
        # system + first user + first assistant + second user
        user_messages = [m for m in messages if m["role"] == "user"]
        assert len(user_messages) >= 2


class TestAgentAudit:
    """Agent logs actions to audit trail."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_logs_command_received_and_completed(self) -> None:
        llm = MockLLM(responses=["Done."])
        audit = SimpleAudit()
        agent = ProductionAgent(llm=llm, audit=audit)

        await agent.run("Do something")

        actions = [e["action"] for e in audit.entries]
        assert "command_received" in actions
        assert "command_completed" in actions

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_audit_entries_have_correlation_id(self) -> None:
        llm = MockLLM(responses=["Done."])
        audit = SimpleAudit()
        agent = ProductionAgent(llm=llm, audit=audit)

        result = await agent.run("Do something")

        for entry in audit.entries:
            assert entry["correlation_id"] == result.correlation_id


class TestAgentResult:
    """AgentResult serialization."""

    @pytest.mark.unit
    def test_to_dict(self) -> None:
        result = AgentResult(
            response="Hello",
            conversation_id="c1",
            correlation_id="r1",
            iterations=1,
            tool_calls=[],
            tokens_used=10,
        )
        d = result.to_dict()
        assert d["response"] == "Hello"
        assert d["conversation_id"] == "c1"
        assert d["tokens_used"] == 10
