"""Mock LLM adapter for testing. No API calls, deterministic responses."""

from __future__ import annotations


class MockLLM:
    """Deterministic LLM for testing. Pops responses from a list.

    Usage:
        llm = MockLLM(responses=["Hello!", "I can help with that."])
        result = await llm.chat([{"role": "user", "content": "Hi"}])
        assert result == "Hello!"
        assert len(llm.call_history) == 1
    """

    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = list(responses) if responses else ["I am a mock LLM."]
        self.call_history: list[dict] = []
        self._call_count = 0

    async def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        """Return next response from the list. Tracks all calls for assertions."""
        self.call_history.append(
            {
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "call_number": self._call_count,
            }
        )

        if self._call_count < len(self.responses):
            response = self.responses[self._call_count]
        else:
            response = "I don't have more responses configured."

        self._call_count += 1
        return response
