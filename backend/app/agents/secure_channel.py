"""Secure inter-agent communication channel using HMAC-SHA256 signatures.

Course reference: Day 6 – Agent Communication Encryption
Ensures messages between specialist agents are tamper-proof and authenticated.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field


@dataclass
class SignedMessage:
    """A message with HMAC-SHA256 signature for integrity verification."""

    from_agent: str
    to_agent: str
    content: str
    signature: str
    timestamp: float

    def to_dict(self) -> dict:
        return {
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "content": self.content,
            "signature": self.signature,
            "timestamp": self.timestamp,
        }


class SecureChannel:
    """Signs and verifies inter-agent messages with HMAC-SHA256.

    Usage::

        ch = SecureChannel(secret="shared-key")
        msg = ch.sign_message("planner", "retriever", "find docs about X")
        assert ch.verify_message(msg)
    """

    def __init__(self, secret: str, max_age_seconds: float = 300.0) -> None:
        self._secret = secret.encode()
        self._max_age = max_age_seconds

    # -- public API -----------------------------------------------------------

    def sign_message(
        self,
        from_agent: str,
        to_agent: str,
        content: str,
    ) -> SignedMessage:
        """Create a signed message between two agents."""
        ts = time.time()
        signature = self._compute_signature(from_agent, to_agent, content, ts)
        return SignedMessage(
            from_agent=from_agent,
            to_agent=to_agent,
            content=content,
            signature=signature,
            timestamp=ts,
        )

    def verify_message(self, message: SignedMessage) -> bool:
        """Verify the HMAC signature and freshness of a message."""
        # Check freshness
        if time.time() - message.timestamp > self._max_age:
            return False

        expected = self._compute_signature(
            message.from_agent,
            message.to_agent,
            message.content,
            message.timestamp,
        )
        return hmac.compare_digest(expected, message.signature)

    # -- internals ------------------------------------------------------------

    def _compute_signature(
        self,
        from_agent: str,
        to_agent: str,
        content: str,
        timestamp: float,
    ) -> str:
        payload = f"{from_agent}:{to_agent}:{content}:{timestamp}"
        return hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()
