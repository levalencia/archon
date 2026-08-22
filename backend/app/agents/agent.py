"""Production AI Agent with ReAct reasoning loop.

The agent follows a Think → Act → Observe cycle:
1. Build context from memory + user input
2. Call LLM to decide: respond directly or call a tool
3. If tool call → check permissions → execute → add result to context → loop back
4. If final answer → return it
5. Max iterations prevent infinite loops; token budget prevents cost overruns

See: https://github.com/levalencia/production-ai-agents/articles/day-02-reasoning-loops/
Concept: ReAct (Reason + Act) loop with iteration caps and cost controls
"""

from __future__ import annotations

import json
import uuid

import structlog

from app.agents.protocols import AuditLog, LLMClient, MemoryStore, PermissionChecker, ToolExecutor
from app.observability.logging import get_correlation_id

logger = structlog.get_logger()

SYSTEM_PROMPT = """You are Archon, a production AI research assistant.

When you need to use a tool, respond ONLY with a JSON object:
{"tool_call": {"name": "tool_name", "parameters": {"key": "value"}}}

When you have enough information to answer, respond with plain text (no JSON).

Available tools:
{tool_descriptions}

Rules:
- Use tools when you need external data or actions
- Always verify information before answering
- Cite sources when available
- If unsure, say so honestly
"""


class AgentResult:
    """Result of an agent run."""

    def __init__(
        self,
        response: str,
        conversation_id: str,
        correlation_id: str,
        iterations: int,
        tool_calls: list[dict],
        tokens_used: int = 0,
        steps: list | None = None,
    ) -> None:
        self.response = response
        self.conversation_id = conversation_id
        self.correlation_id = correlation_id
        self.iterations = iterations
        self.tool_calls = tool_calls
        self.steps = steps or []
        self.tokens_used = tokens_used

    def to_dict(self) -> dict:
        return {
            "response": self.response,
            "conversation_id": self.conversation_id,
            "correlation_id": self.correlation_id,
            "iterations": self.iterations,
            "tool_calls": self.tool_calls,
            "tokens_used": self.tokens_used,
        }


class ProductionAgent:
    """ReAct agent with DI for all components. Zero framework dependencies.

    All dependencies are injected via __init__ using Protocol interfaces.
    The agent has no knowledge of which LLM, memory store, or tools it uses.
    """

    MAX_ITERATIONS = 5
    TOKEN_BUDGET = 10000

    def __init__(
        self,
        llm: LLMClient,
        memory: MemoryStore | None = None,
        tools: ToolExecutor | None = None,
        audit: AuditLog | None = None,
        permissions: PermissionChecker | None = None,
        agent_id: str = "archon",
        max_iterations: int | None = None,
        token_budget: int | None = None,
        system_prompt_extra: str = "",
    ) -> None:
        self.llm = llm
        self.memory = memory
        self.tools = tools
        self.audit = audit
        self.permissions = permissions
        self.agent_id = agent_id
        self.max_iterations = max_iterations or self.MAX_ITERATIONS
        self.token_budget = token_budget or self.TOKEN_BUDGET
        self.system_prompt_extra = system_prompt_extra
        self._steps: list[dict] = []

    async def run(
        self,
        user_input: str,
        conversation_id: str | None = None,
        images: list[str] | None = None,
    ) -> AgentResult:
        """Execute the ReAct loop for a user message."""
        conversation_id = conversation_id or str(uuid.uuid4())
        correlation_id = get_correlation_id()
        tool_calls_made: list[dict] = []
        total_tokens = 0

        # Log command received
        if self.audit:
            await self.audit.log(
                agent_id=self.agent_id,
                action="command_received",
                resource="user_input",
                parameters={"input_length": len(user_input)},
                correlation_id=correlation_id,
            )

        # Build initial context
        messages = await self._build_context(user_input, conversation_id)

        # ReAct loop
        for iteration in range(1, self.max_iterations + 1):
            logger.info(
                "react_iteration",
                iteration=iteration,
                max_iterations=self.max_iterations,
                messages_count=len(messages),
                correlation_id=correlation_id,
            )

            # Call LLM
            response = await self.llm.chat(
                messages, max_tokens=min(4096, self.token_budget - total_tokens)
            )
            total_tokens += self._estimate_tokens(response)

            # Check token budget
            if total_tokens >= self.token_budget:
                logger.warning(
                    "token_budget_exceeded",
                    total_tokens=total_tokens,
                    budget=self.token_budget,
                    correlation_id=correlation_id,
                )
                break

            # Parse: tool call or final answer?
            tool_call = self._parse_tool_call(response)

            if tool_call is None:
                # Final answer
                logger.info(
                    "react_final_answer",
                    iteration=iteration,
                    total_tokens=total_tokens,
                    correlation_id=correlation_id,
                )

                # Store in memory
                if self.memory:
                    await self.memory.store(conversation_id, "user", user_input)
                    await self.memory.store(conversation_id, "assistant", response)

                # Log completion
                if self.audit:
                    await self.audit.log(
                        agent_id=self.agent_id,
                        action="command_completed",
                        resource="user_input",
                        parameters={"iterations": iteration, "tokens": total_tokens},
                        correlation_id=correlation_id,
                    )

                return AgentResult(
                    response=response,
                    conversation_id=conversation_id,
                    correlation_id=correlation_id,
                    iterations=iteration,
                    tool_calls=tool_calls_made,
                    tokens_used=total_tokens,
                )

            # Tool call path
            tool_name = tool_call["name"]
            tool_params = tool_call.get("parameters", {})

            self._steps.append(
                {
                    "type": "tool_call",
                    "agent": "archon",
                    "detail": f"Called tool: {tool_name}",
                    "content": f"Tool {tool_name} returned result",
                }
            )
            logger.info(
                "react_tool_call",
                tool=tool_name,
                params=tool_params,
                iteration=iteration,
                correlation_id=correlation_id,
            )

            # Execute tool (with permission check inside ToolExecutor)
            if self.tools:
                try:
                    tool_result = await self.tools.execute(tool_name, tool_params)
                    tool_calls_made.append(
                        {
                            "tool": tool_name,
                            "parameters": tool_params,
                            "result": tool_result,
                            "status": "success",
                        }
                    )
                except PermissionError as e:
                    tool_result = {"error": f"Permission denied: {e}"}
                    tool_calls_made.append(
                        {
                            "tool": tool_name,
                            "parameters": tool_params,
                            "result": tool_result,
                            "status": "denied",
                        }
                    )
                    if self.audit:
                        await self.audit.log(
                            agent_id=self.agent_id,
                            action="permission_denied",
                            resource=tool_name,
                            parameters=tool_params,
                            result="denied",
                            correlation_id=correlation_id,
                            security_level="warning",
                        )
                except Exception as e:
                    tool_result = {"error": str(e)}
                    tool_calls_made.append(
                        {
                            "tool": tool_name,
                            "parameters": tool_params,
                            "result": tool_result,
                            "status": "error",
                        }
                    )
            else:
                tool_result = {"error": f"No tool executor configured for '{tool_name}'"}
                tool_calls_made.append(
                    {
                        "tool": tool_name,
                        "parameters": tool_params,
                        "result": tool_result,
                        "status": "error",
                    }
                )

            # Add tool result to context and continue loop
            messages.append({"role": "assistant", "content": response})
            messages.append(
                {
                    "role": "user",
                    "content": f"Tool '{tool_name}' returned: {json.dumps(tool_result)}",
                }
            )

        # Max iterations reached
        logger.warning(
            "react_max_iterations",
            max_iterations=self.max_iterations,
            tool_calls=len(tool_calls_made),
            correlation_id=correlation_id,
        )

        fallback = (
            "I reached the maximum number of reasoning steps. "
            "Here is what I found so far based on the tool results."
        )

        if self.memory:
            await self.memory.store(conversation_id, "user", user_input)
            await self.memory.store(conversation_id, "assistant", fallback)

        return AgentResult(
            response=fallback,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            iterations=self.max_iterations,
            tool_calls=tool_calls_made,
            tokens_used=total_tokens,
            steps=self._steps,
        )

    async def _build_context(self, user_input: str, conversation_id: str) -> list[dict[str, str]]:
        """Build message context from system prompt + memory + user input."""
        messages: list[dict[str, str]] = []

        # System prompt with tool descriptions
        tool_descriptions = "None configured"
        if self.tools:
            tools = self.tools.list_tools()
            if tools:
                tool_descriptions = json.dumps(tools, indent=2)

        messages.append(
            {
                "role": "system",
                "content": SYSTEM_PROMPT.replace("{tool_descriptions}", tool_descriptions),
            }
        )

        # Memory context
        if self.memory:
            history = await self.memory.retrieve(conversation_id, limit=20)
            messages.extend(history)

        # Current user input
        messages.append({"role": "user", "content": user_input})

        return messages

    def _parse_tool_call(self, response: str) -> dict | None:
        """Parse a tool call from LLM response. Returns None if final answer."""
        response = response.strip()

        # Try to parse as JSON with tool_call
        try:
            data = json.loads(response)
            if isinstance(data, dict) and "tool_call" in data:
                tc = data["tool_call"]
                if "name" in tc:
                    return tc
        except (json.JSONDecodeError, KeyError):
            pass

        return None

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimation. ~1.3 tokens per word."""
        return int(len(text.split()) * 1.3)
