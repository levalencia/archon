"""Multi-agent orchestration: Coordinator + specialist agents.

The Coordinator uses a ReAct loop to decide which specialist to delegate to.
Specialists are registered as tools — "tools all the way down".

Agents:
- Coordinator: decides what to do, delegates to specialists
- PlannerAgent: decomposes complex queries into sub-tasks
- RetrieverAgent: searches documents via RAG pipeline
- ValidatorAgent: checks for PII, fact consistency, guardrails
- SynthesizerAgent: produces final answer with citations

See: https://github.com/levalencia/production-ai-agents/
Concept: Multi-agent orchestration (Phase 4)
Course reference: Advanced Architectures L46-L57
"""

from __future__ import annotations

import json

import structlog

from app.agents.protocols import LLMClient

logger = structlog.get_logger()


class SpecialistAgent:
    """Base class for specialist agents. Each specialist has a role and LLM."""

    def __init__(
        self,
        name: str,
        role: str,
        llm: LLMClient,
        system_prompt: str = "",
    ) -> None:
        self.name = name
        self.role = role
        self.llm = llm
        self.system_prompt = system_prompt

    async def execute(self, task: str, context: dict | None = None) -> dict:
        """Execute the specialist's task."""
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})

        user_content = task
        if context:
            user_content += f"\n\nContext: {json.dumps(context)}"

        messages.append({"role": "user", "content": user_content})

        response = await self.llm.chat(messages)

        logger.info(
            "specialist_executed",
            agent=self.name,
            role=self.role,
            task_length=len(task),
            response_length=len(response),
        )

        return {
            "agent": self.name,
            "role": self.role,
            "response": response,
            "task": task,
        }


class PlannerAgent(SpecialistAgent):
    """Decomposes complex queries into sub-tasks."""

    def __init__(self, llm: LLMClient) -> None:
        super().__init__(
            name="planner",
            role="query_decomposition",
            llm=llm,
            system_prompt=(
                "You are a planning agent. Break down complex questions into "
                "2-4 simple sub-questions. Return a JSON list of strings."
            ),
        )


class RetrieverAgent(SpecialistAgent):
    """Searches documents and returns relevant information."""

    def __init__(self, llm: LLMClient) -> None:
        super().__init__(
            name="retriever",
            role="information_retrieval",
            llm=llm,
            system_prompt=(
                "You are a retrieval agent. Given a question and context, "
                "identify the most relevant information and cite sources."
            ),
        )


class ValidatorAgent(SpecialistAgent):
    """Validates responses for accuracy, PII, and compliance."""

    def __init__(self, llm: LLMClient) -> None:
        super().__init__(
            name="validator",
            role="quality_validation",
            llm=llm,
            system_prompt=(
                "You are a validation agent. Check if the response is accurate, "
                "contains no PII, and is safe to show to users. "
                'Respond with: {"approved": true/false, "reason": "..."}'
            ),
        )


class SynthesizerAgent(SpecialistAgent):
    """Produces final answers with citations."""

    def __init__(self, llm: LLMClient) -> None:
        super().__init__(
            name="synthesizer",
            role="answer_synthesis",
            llm=llm,
            system_prompt=(
                "You are a synthesis agent. Combine information from multiple "
                "sources into a clear, well-cited answer. Always mention sources."
            ),
        )


class AgentCoordinator:
    """Orchestrates multiple specialist agents.

    The Coordinator decides which specialists to invoke based on the query.
    It follows a pipeline: Plan → Retrieve → Validate → Synthesize.
    """

    def __init__(
        self,
        planner: PlannerAgent,
        retriever: RetrieverAgent,
        validator: ValidatorAgent,
        synthesizer: SynthesizerAgent,
    ) -> None:
        self.planner = planner
        self.retriever = retriever
        self.validator = validator
        self.synthesizer = synthesizer
        self._agents = {
            "planner": planner,
            "retriever": retriever,
            "validator": validator,
            "synthesizer": synthesizer,
        }

    async def orchestrate(
        self,
        query: str,
        context: dict | None = None,
    ) -> dict:
        """Run the multi-agent pipeline for a query.

        Pipeline: Plan → Retrieve → Validate → Synthesize
        """
        steps: list[dict] = []

        # Step 1: Plan
        logger.info("coordinator_step", step="plan", query=query[:100])
        plan_result = await self.planner.execute(f"Break down this question: {query}")
        steps.append(plan_result)

        # Step 2: Retrieve
        logger.info("coordinator_step", step="retrieve")
        retrieve_result = await self.retriever.execute(
            query,
            context={"plan": plan_result["response"]},
        )
        steps.append(retrieve_result)

        # Step 3: Validate
        logger.info("coordinator_step", step="validate")
        validate_result = await self.validator.execute(
            f"Validate this response: {retrieve_result['response']}",
            context={"original_query": query},
        )
        steps.append(validate_result)

        # Step 4: Synthesize
        logger.info("coordinator_step", step="synthesize")
        synth_result = await self.synthesizer.execute(
            f"Create a final answer for: {query}",
            context={
                "retrieved": retrieve_result["response"],
                "validation": validate_result["response"],
            },
        )
        steps.append(synth_result)

        return {
            "answer": synth_result["response"],
            "steps": steps,
            "agents_used": [s["agent"] for s in steps],
            "pipeline": "plan → retrieve → validate → synthesize",
        }

    def list_agents(self) -> list[dict]:
        """List all registered specialist agents."""
        return [{"name": agent.name, "role": agent.role} for agent in self._agents.values()]
