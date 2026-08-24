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

TODAY'S DATE: {current_date}
IMPORTANT: The current year is 2026.
TOOL BUDGET: You have a maximum of {tool_budget} tool calls per response. Plan efficiently.
When you have used most of your budget, stop calling tools and synthesize your answer from what you have, NOT 2025. Always use 2026 when searching for current news or events.

CRITICAL RULES:
1. You MUST use tools when available. NEVER make up data or search results.
2. For ANY math question, ALWAYS call the calculator tool. Do NOT calculate in your head.
3. For ANY question about current events, dates, or web information, ALWAYS call web_search first.

WEB SEARCH BEST PRACTICES:
- ALWAYS include the current date/month/year in search queries for news (e.g. "agosto 2026" or "August 2026")
- Adapt the search query LANGUAGE to the country/region being searched:
  * News about Germany → search in German: "Nachrichten Deutschland heute August 2026"
  * News about France → search in French: "actualités France aujourd'hui août 2026"
  * News about Brazil → search in Portuguese: "notícias Brasil hoje agosto 2026"
  * News about Japan → search in English but include country: "Japan news today August 2026"
  * News about Colombia → search in Spanish: "noticias Colombia hoy agosto 2026"
- For multi-country queries, be EFFICIENT:
  * Group countries by region: "noticias Sudamérica agosto 2026" instead of 10 separate searches
  * Maximum 3-4 web searches per query — combine related countries
  * Example: instead of searching each of 10 countries separately, do:
    Search 1: "smallest countries world news August 2026"
    Search 2: "Vatican Monaco Malta news August 2026"
    Search 3: "Pacific island nations news August 2026"
  * Be efficient — you have a limited tool budget
- ALWAYS respond in the SAME language the user used, regardless of search language
4. For ANY date/time question, ALWAYS call the datetime tool first.
5. After calling a tool, use its REAL result in your answer.

TOOL CALLING FORMAT (you MUST output exactly this JSON when calling a tool):
{"tool_call": {"name": "TOOL_NAME", "parameters": {"param": "value"}}}

Available tools: calculator, datetime, web_search, read_file, image_gen.

Calculator supports: +, -, *, /, ^, sqrt(), pi, abs(), parentheses.
Example: {"tool_call": {"name": "calculator", "parameters": {"expression": "10000*(1.075**5)"}}}

When you need to use a tool, respond ONLY with a JSON object:
{"tool_call": {"name": "tool_name", "parameters": {"key": "value"}}}

When you have enough information to answer, respond with plain text (no JSON).

ARTIFACT GENERATION:
When the user asks you to create, write, or generate code, HTML, SVG, or any document:
- Always wrap code in triple backtick blocks with the language identifier.
- For complete HTML pages, include the full <!DOCTYPE html> document.
- For diagrams, use ```mermaid blocks.
- Be thorough: generate complete, runnable code, not snippets.
- The system will automatically detect and display these as interactive artifacts.

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

    MAX_ITERATIONS = 20
    MAX_TOOL_CALLS = 8
    REQUEST_TIMEOUT = 90  # seconds
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
        self._tool_calls_remaining = self.MAX_TOOL_CALLS
        self._start_time = None
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
        import time as _time

        self._start_time = _time.monotonic()
        self._tool_calls_remaining = self.MAX_TOOL_CALLS
        total_tokens = 0
        _run_images = images

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

            # Inject images into user message for vision (first iteration only)
            if _run_images and iteration == 1:
                for msg in reversed(messages):
                    if msg["role"] == "user":
                        msg["images"] = _run_images
                        break

            # Call LLM
            # Auto-compact context if too long
            from app.services.auto_compact import auto_compact_context

            messages, compact_stats = await auto_compact_context(
                messages,
                llm_chat_fn=self.llm.chat,
            )

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

            # Check request timeout
            import time as _time

            if self._start_time and (_time.monotonic() - self._start_time) > self.REQUEST_TIMEOUT:
                logger.warning("react_timeout", elapsed=_time.monotonic() - self._start_time)
                response = f"I've been working for over {self.REQUEST_TIMEOUT}s. Here's what I found so far."  # noqa: E501
                break

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

        # Inject persistent memory into system prompt
        from app.memory.persistent import get_persistent_memory

        persistent = get_persistent_memory()
        memory_context = persistent.get_context_text()
        memory_section = ""
        if memory_context:
            memory_section = f"\n\nPERSISTENT MEMORY (facts about the user):\n{memory_context}\n"

        messages.append(
            {
                "role": "system",
                "content": (
                    SYSTEM_PROMPT.replace("{tool_descriptions}", tool_descriptions) + memory_section
                ).replace(
                    "{current_date}",
                    __import__("datetime")
                    .datetime.now(__import__("zoneinfo").ZoneInfo("Europe/Brussels"))
                    .strftime("%A, %B %d, %Y at %H:%M %Z"),
                ),
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
        """Parse a tool call from LLM response. Returns None if final answer.

        Handles: pure JSON, JSON embedded in text, JSON in code blocks.
        """
        response = response.strip()

        # Try 1: Full response is JSON
        try:
            data = json.loads(response)
            if isinstance(data, dict) and "tool_call" in data:
                tc = data["tool_call"]
                if "name" in tc:
                    return tc
        except (json.JSONDecodeError, KeyError):
            pass

        # Try 2: Find JSON object in text (Claude often wraps in text)
        import re

        json_matches = re.findall(
            r'\{\s*"tool_call"\s*:\s*\{[^}]*"name"\s*:[^}]*\}\s*\}',
            response,
        )
        for match in json_matches:
            try:
                data = json.loads(match)
                if "tool_call" in data and "name" in data["tool_call"]:
                    return data["tool_call"]
            except json.JSONDecodeError:
                continue

        # Try 3: Find any {"tool_call": ...} pattern more flexibly
        idx = response.find('"tool_call"')
        if idx >= 0:
            # Walk back to find opening brace
            start = response.rfind("{", 0, idx)
            if start >= 0:
                # Find matching closing braces
                depth = 0
                for i in range(start, len(response)):
                    if response[i] == "{":
                        depth += 1
                    elif response[i] == "}":
                        depth -= 1
                        if depth == 0:
                            try:
                                data = json.loads(response[start : i + 1])
                                if "tool_call" in data:
                                    return data["tool_call"]
                            except json.JSONDecodeError:
                                pass
                            break

        return None

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimation. ~1.3 tokens per word."""
        return int(len(text.split()) * 1.3)
