"""Tests for multi-agent orchestration."""

from __future__ import annotations

import pytest

from app.agents.mock_llm import MockLLM
from app.agents.multi_agent import (
    AgentCoordinator,
    PlannerAgent,
    RetrieverAgent,
    SpecialistAgent,
    SynthesizerAgent,
    ValidatorAgent,
)


class TestSpecialistAgent:
    """Base specialist agent tests."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_basic_execution(self) -> None:
        llm = MockLLM(responses=["I found the answer."])
        agent = SpecialistAgent(name="test", role="testing", llm=llm)

        result = await agent.execute("What is 2+2?")

        assert result["agent"] == "test"
        assert result["role"] == "testing"
        assert result["response"] == "I found the answer."

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_execution_with_context(self) -> None:
        llm = MockLLM(responses=["Context-aware answer."])
        agent = SpecialistAgent(name="test", role="testing", llm=llm)

        result = await agent.execute("Query", context={"key": "value"})

        assert result["response"] == "Context-aware answer."
        # Verify context was passed to LLM
        last_call = llm.call_history[-1]
        assert "value" in last_call["messages"][-1]["content"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_system_prompt_included(self) -> None:
        llm = MockLLM(responses=["ok"])
        agent = SpecialistAgent(
            name="test",
            role="testing",
            llm=llm,
            system_prompt="You are a test agent.",
        )

        await agent.execute("Do something")

        last_call = llm.call_history[-1]
        assert last_call["messages"][0]["role"] == "system"
        assert "test agent" in last_call["messages"][0]["content"]


class TestSpecialistTypes:
    """Test each specialist type creates correctly."""

    @pytest.mark.unit
    def test_planner_agent(self) -> None:
        llm = MockLLM()
        agent = PlannerAgent(llm=llm)
        assert agent.name == "planner"
        assert agent.role == "query_decomposition"

    @pytest.mark.unit
    def test_retriever_agent(self) -> None:
        llm = MockLLM()
        agent = RetrieverAgent(llm=llm)
        assert agent.name == "retriever"
        assert agent.role == "information_retrieval"

    @pytest.mark.unit
    def test_validator_agent(self) -> None:
        llm = MockLLM()
        agent = ValidatorAgent(llm=llm)
        assert agent.name == "validator"
        assert agent.role == "quality_validation"

    @pytest.mark.unit
    def test_synthesizer_agent(self) -> None:
        llm = MockLLM()
        agent = SynthesizerAgent(llm=llm)
        assert agent.name == "synthesizer"
        assert agent.role == "answer_synthesis"


class TestAgentCoordinator:
    """Multi-agent coordination tests."""

    @pytest.fixture
    def coordinator(self) -> AgentCoordinator:
        llm = MockLLM(
            responses=[
                "Sub-questions: 1) What is X? 2) Why does X matter?",  # Planner
                "Retrieved: X is a concept in computer science.",  # Retriever
                '{"approved": true, "reason": "factually correct"}',  # Validator
                "Final answer: X is important because...",  # Synthesizer
            ]
        )
        return AgentCoordinator(
            planner=PlannerAgent(llm=llm),
            retriever=RetrieverAgent(llm=llm),
            validator=ValidatorAgent(llm=llm),
            synthesizer=SynthesizerAgent(llm=llm),
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_full_pipeline(self, coordinator: AgentCoordinator) -> None:
        result = await coordinator.orchestrate("What is X and why does it matter?")

        assert "answer" in result
        assert result["answer"] == "Final answer: X is important because..."
        assert len(result["steps"]) == 4
        assert result["agents_used"] == ["planner", "retriever", "validator", "synthesizer"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_pipeline_order(self, coordinator: AgentCoordinator) -> None:
        result = await coordinator.orchestrate("Test query")

        agents = [s["agent"] for s in result["steps"]]
        assert agents == ["planner", "retriever", "validator", "synthesizer"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_each_step_has_response(self, coordinator: AgentCoordinator) -> None:
        result = await coordinator.orchestrate("Test")

        for step in result["steps"]:
            assert "response" in step
            assert len(step["response"]) > 0

    @pytest.mark.unit
    def test_list_agents(self, coordinator: AgentCoordinator) -> None:
        agents = coordinator.list_agents()
        assert len(agents) == 4
        names = {a["name"] for a in agents}
        assert names == {"planner", "retriever", "validator", "synthesizer"}

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_pipeline_string(self, coordinator: AgentCoordinator) -> None:
        result = await coordinator.orchestrate("Query")
        assert "plan" in result["pipeline"]
        assert "synthesize" in result["pipeline"]
