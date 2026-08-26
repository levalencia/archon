"""LLM adapter fallback chain: graceful degradation when primary LLM is down.

Tries adapters in order. If one fails, falls back to the next.
Logs failures for observability.
"""

from __future__ import annotations

import structlog

from app.agents.protocols import LLMClient
from app.observability.logging import safe_exception_metadata

logger = structlog.get_logger()


class FallbackLLMChain:
    """Try multiple LLM adapters in order. First success wins.

    Usage:
        chain = FallbackLLMChain([
            FoundryAdapter(...),
            OpenAIAdapter(...),
            OllamaAdapter(...),
        ])
        response = await chain.chat(messages)
    """

    def __init__(self, adapters: list[LLMClient]) -> None:
        if not adapters:
            msg = "At least one adapter required"
            raise ValueError(msg)
        self.adapters = adapters
        self._failures: dict[int, int] = {}

    async def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        """Try each adapter in order. Return first successful response."""
        errors = []

        for i, adapter in enumerate(self.adapters):
            adapter_name = type(adapter).__name__
            try:
                response = await adapter.chat(messages, max_tokens, temperature=temperature)
                if i > 0:
                    logger.info(
                        "llm_fallback_success",
                        adapter=adapter_name,
                        position=i,
                        failures_skipped=i,
                    )
                return response

            except Exception as exc:
                self._failures[i] = self._failures.get(i, 0) + 1
                errors.append(f"{adapter_name}: {exc}")
                logger.warning(
                    "llm_adapter_failed",
                    adapter=adapter_name,
                    position=i,
                    **safe_exception_metadata(exc, "provider_request_failed"),
                    total_failures=self._failures[i],
                )

        # All adapters failed
        error_summary = "; ".join(errors)
        logger.error("llm_all_adapters_failed", provider_count=len(errors))
        return f"[All LLM providers failed: {error_summary}]"

    def get_stats(self) -> dict:
        """Get failure stats per adapter."""
        return {
            "adapters": [type(a).__name__ for a in self.adapters],
            "failures": dict(self._failures),
        }
