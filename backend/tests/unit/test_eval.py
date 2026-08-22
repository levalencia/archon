"""Tests for evaluation harness."""

from __future__ import annotations

import pytest

from app.agents.agent import ProductionAgent
from app.agents.mock_llm import MockLLM
from app.eval.harness import EvalCase, EvalHarness


class TestEvalCase:
    """EvalCase data structure tests."""

    @pytest.mark.unit
    def test_basic_case(self) -> None:
        case = EvalCase(id="q1", input="What is 2+2?", expected_contains=["4"])
        assert case.id == "q1"
        assert case.expected_contains == ["4"]

    @pytest.mark.unit
    def test_case_with_tags(self) -> None:
        case = EvalCase(id="q1", input="test", tags=["math", "basic"])
        assert "math" in case.tags


class TestEvalHarness:
    """Evaluation harness tests."""

    @pytest.fixture
    def simple_agent(self) -> ProductionAgent:
        llm = MockLLM(
            responses=[
                "The answer is 4.",
                "Python is a programming language.",
                "I cannot help with that request.",
            ]
            * 5
        )
        return ProductionAgent(llm=llm)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_single_case_pass(self, simple_agent: ProductionAgent) -> None:
        harness = EvalHarness(agent_fn=simple_agent.run)
        harness.add_case(
            EvalCase(
                id="q1",
                input="What is 2+2?",
                expected_contains=["4"],
            )
        )

        summary = await harness.run()
        assert summary.total == 1
        assert summary.passed == 1
        assert summary.pass_rate == 1.0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_single_case_fail(self, simple_agent: ProductionAgent) -> None:
        harness = EvalHarness(agent_fn=simple_agent.run)
        harness.add_case(
            EvalCase(
                id="q1",
                input="What is 2+2?",
                expected_contains=["42"],  # Wrong expectation
            )
        )

        summary = await harness.run()
        assert summary.total == 1
        assert summary.failed == 1

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_multiple_cases(self, simple_agent: ProductionAgent) -> None:
        harness = EvalHarness(agent_fn=simple_agent.run)
        harness.add_cases(
            [
                EvalCase(id="q1", input="Math", expected_contains=["4"]),
                EvalCase(id="q2", input="Python", expected_contains=["programming"]),
            ]
        )

        summary = await harness.run()
        assert summary.total == 2

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_not_contains_check(self, simple_agent: ProductionAgent) -> None:
        harness = EvalHarness(agent_fn=simple_agent.run)
        harness.add_case(
            EvalCase(
                id="q1",
                input="What is 2+2?",
                expected_not_contains=["error", "fail"],
            )
        )

        summary = await harness.run()
        assert summary.passed == 1

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_quality_gate_passes(self, simple_agent: ProductionAgent) -> None:
        harness = EvalHarness(agent_fn=simple_agent.run, quality_threshold=0.5)
        harness.add_case(
            EvalCase(
                id="q1",
                input="test",
                expected_contains=["answer"],
            )
        )

        summary = await harness.run()
        assert harness.quality_gate(summary) is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_quality_gate_fails(self, simple_agent: ProductionAgent) -> None:
        harness = EvalHarness(agent_fn=simple_agent.run, quality_threshold=1.0)
        harness.add_case(
            EvalCase(
                id="q1",
                input="test",
                expected_contains=["nonexistent_word"],
            )
        )

        summary = await harness.run()
        assert harness.quality_gate(summary) is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_summary_has_avg_latency(self, simple_agent: ProductionAgent) -> None:
        harness = EvalHarness(agent_fn=simple_agent.run)
        harness.add_case(EvalCase(id="q1", input="test"))

        summary = await harness.run()
        assert summary.avg_latency_ms >= 0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tag_grouping(self, simple_agent: ProductionAgent) -> None:
        harness = EvalHarness(agent_fn=simple_agent.run)
        harness.add_cases(
            [
                EvalCase(id="q1", input="test1", tags=["math"]),
                EvalCase(id="q2", input="test2", tags=["math", "basic"]),
            ]
        )

        summary = await harness.run()
        assert "math" in summary.tags
        assert summary.tags["math"]["total"] == 2

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_error_handling(self) -> None:
        """Agent that raises should not crash the harness."""

        async def failing_agent(query: str) -> dict:
            msg = "LLM connection failed"
            raise ConnectionError(msg)

        harness = EvalHarness(agent_fn=failing_agent)
        harness.add_case(EvalCase(id="q1", input="test"))

        summary = await harness.run()
        assert summary.failed == 1
        assert summary.results[0].error is not None
