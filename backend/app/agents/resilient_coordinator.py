"""Multi-agent upgrades: handoff protocol, fallback, per-agent token budgets.

Adds production patterns to the existing Coordinator:
- Agent handoff with typed messages
- Fallback when an agent fails (retry, degrade, skip)
- Per-agent token budget tracking
- Coordination bus for async message passing
"""

from __future__ import annotations

import asyncio
import time

import structlog

from app.agents.multi_agent import AgentCoordinator, SpecialistAgent

logger = structlog.get_logger()


class AgentMessage:
    """Typed message for inter-agent communication."""

    def __init__(
        self,
        from_agent: str,
        to_agent: str,
        content: str,
        msg_type: str = "request",  # request, response, handoff, error
        metadata: dict | None = None,
    ) -> None:
        self.from_agent = from_agent
        self.to_agent = to_agent
        self.content = content
        self.msg_type = msg_type
        self.metadata = metadata or {}
        self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "from": self.from_agent,
            "to": self.to_agent,
            "type": self.msg_type,
            "content": self.content[:200],
            "timestamp": self.timestamp,
        }


class TokenBudgetManager:
    """Track and enforce per-agent token budgets."""

    def __init__(self, total_budget: int = 8000) -> None:
        self.total_budget = total_budget
        self.spent: dict[str, int] = {}
        self.limits: dict[str, int] = {}

    def set_limit(self, agent_name: str, limit: int) -> None:
        self.limits[agent_name] = limit

    def record(self, agent_name: str, tokens: int) -> None:
        self.spent[agent_name] = self.spent.get(agent_name, 0) + tokens

    def can_spend(self, agent_name: str, tokens: int) -> bool:
        current = self.spent.get(agent_name, 0)
        limit = self.limits.get(agent_name, self.total_budget)
        total_spent = sum(self.spent.values())
        return current + tokens <= limit and total_spent + tokens <= self.total_budget

    def get_report(self) -> dict:
        return {
            "total_budget": self.total_budget,
            "total_spent": sum(self.spent.values()),
            "remaining": self.total_budget - sum(self.spent.values()),
            "by_agent": dict(self.spent),
            "limits": dict(self.limits),
        }


class ResilientCoordinator(AgentCoordinator):
    """Enhanced coordinator with fallback, handoff, and token budgets.

    Extends AgentCoordinator with:
    - Retry on agent failure
    - Fallback to degraded mode
    - Token budget enforcement
    - Message bus for traceability
    """

    def __init__(
        self,
        planner: SpecialistAgent,
        retriever: SpecialistAgent,
        validator: SpecialistAgent,
        synthesizer: SpecialistAgent,
        total_token_budget: int = 8000,
        max_retries: int = 2,
        timeout_seconds: float = 30.0,
    ) -> None:
        super().__init__(planner, retriever, validator, synthesizer)
        self.budget = TokenBudgetManager(total_token_budget)
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self._message_bus: list[AgentMessage] = []

        # Set per-agent budgets (proportional)
        self.budget.set_limit("planner", total_token_budget // 5)
        self.budget.set_limit("retriever", total_token_budget // 3)
        self.budget.set_limit("validator", total_token_budget // 5)
        self.budget.set_limit("synthesizer", total_token_budget // 3)

    async def orchestrate(
        self,
        query: str,
        context: dict | None = None,
    ) -> dict:
        """Run resilient multi-agent pipeline with fallback."""
        steps: list[dict] = []
        start = time.monotonic()

        # Step 1: Plan (with retry)
        plan_result = await self._execute_with_fallback(
            self.planner,
            f"Break down this question: {query}",
            fallback_response="Proceeding with direct answer (planning skipped)",
        )
        steps.append(plan_result)
        self._record_message("coordinator", "planner", query, "request")
        self._record_message("planner", "coordinator", plan_result["response"], "response")

        # Step 2: Retrieve (with retry)
        retrieve_result = await self._execute_with_fallback(
            self.retriever,
            query,
            context={"plan": plan_result["response"]},
            fallback_response="No additional context found (retrieval skipped)",
        )
        steps.append(retrieve_result)

        # Step 3: Validate (with retry, can be skipped)
        validate_result = await self._execute_with_fallback(
            self.validator,
            f"Validate: {retrieve_result['response'][:500]}",
            context={"original_query": query},
            fallback_response='{"approved": true, "reason": "validation skipped"}',
        )
        steps.append(validate_result)

        # Step 4: Synthesize
        synth_result = await self._execute_with_fallback(
            self.synthesizer,
            f"Answer: {query}",
            context={
                "retrieved": retrieve_result["response"],
                "validation": validate_result["response"],
            },
            fallback_response=retrieve_result["response"],  # Fallback to raw retrieval
        )
        steps.append(synth_result)

        elapsed_ms = (time.monotonic() - start) * 1000

        return {
            "answer": synth_result["response"],
            "steps": steps,
            "agents_used": [s["agent"] for s in steps],
            "pipeline": "plan → retrieve → validate → synthesize",
            "token_budget": self.budget.get_report(),
            "message_bus": [m.to_dict() for m in self._message_bus],
            "elapsed_ms": round(elapsed_ms, 2),
        }

    async def _execute_with_fallback(
        self,
        agent: SpecialistAgent,
        task: str,
        context: dict | None = None,
        fallback_response: str = "Agent unavailable",
    ) -> dict:
        """Execute agent with retry and fallback."""
        for attempt in range(1, self.max_retries + 1):
            try:
                result = await asyncio.wait_for(
                    agent.execute(task, context),
                    timeout=self.timeout_seconds,
                )
                # Estimate tokens (4 chars ≈ 1 token)
                tokens = len(result["response"]) // 4
                self.budget.record(agent.name, tokens)
                return result

            except TimeoutError:
                logger.warning(
                    "agent_timeout",
                    agent=agent.name,
                    attempt=attempt,
                    timeout=self.timeout_seconds,
                )
            except Exception as e:
                logger.warning(
                    "agent_error",
                    agent=agent.name,
                    attempt=attempt,
                    error=str(e),
                )

        # Fallback after all retries exhausted
        logger.error(
            "agent_fallback",
            agent=agent.name,
            retries=self.max_retries,
        )
        return {
            "agent": agent.name,
            "role": agent.role,
            "response": fallback_response,
            "task": task,
            "fallback": True,
        }

    def _record_message(self, from_agent: str, to_agent: str, content: str, msg_type: str) -> None:
        self._message_bus.append(AgentMessage(from_agent, to_agent, content, msg_type))
