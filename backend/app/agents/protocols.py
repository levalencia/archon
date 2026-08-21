"""Core Protocol definitions (interfaces). Zero framework dependencies.

Every component in Archon depends on these Protocols, never on concrete implementations.
This is how we achieve vendor-neutral, testable, swappable architecture.

See: https://github.com/levalencia/production-ai-agents/articles/day-01-anatomy-of-production-agent/
Concept: 6-layer architecture (Model, Orchestration, Tools, Memory, Guardrails, Observability)
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    """Vendor-neutral LLM interface. Adapters for OpenAI, Anthropic, Foundry, Ollama."""

    async def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        """Send messages and get a text response."""
        ...


@runtime_checkable
class MemoryStore(Protocol):
    """Conversation memory storage."""

    async def store(self, conversation_id: str, role: str, content: str) -> None:
        """Store a message in conversation history."""
        ...

    async def retrieve(self, conversation_id: str, limit: int = 50) -> list[dict[str, str]]:
        """Retrieve recent messages for a conversation."""
        ...


@runtime_checkable
class ToolExecutor(Protocol):
    """Secure tool execution registry."""

    async def execute(self, tool_name: str, parameters: dict) -> dict:
        """Execute a registered tool with permission checks."""
        ...

    def list_tools(self) -> list[dict]:
        """List available tools with their schemas."""
        ...


@runtime_checkable
class AuditLog(Protocol):
    """Structured audit logging with correlation IDs."""

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
        """Log an auditable action."""
        ...


@runtime_checkable
class PermissionChecker(Protocol):
    """Permission checking for agent actions."""

    async def check(self, agent_id: str, resource: str, action: str, **kwargs: object) -> bool:
        """Check if an agent is allowed to perform an action."""
        ...


@runtime_checkable
class GuardrailEngine(Protocol):
    """Input/output guardrail validation."""

    async def check_input(self, text: str) -> dict:
        """Validate input. Returns {allowed: bool, reason: str}."""
        ...

    async def check_output(self, text: str) -> dict:
        """Validate output. Returns {allowed: bool, reason: str, redacted: str}."""
        ...
