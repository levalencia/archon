"""Multi-agent authentication: token-based permission control for specialists.

Course reference: Day 15 – Multi-Agent Auth
Each specialist receives a scoped token that limits what operations it can perform.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


# Default permission sets per role
ROLE_PERMISSIONS: dict[str, list[str]] = {
    "query_decomposition": ["plan", "decompose"],
    "information_retrieval": ["search", "retrieve"],
    "quality_validation": ["evaluate", "flag"],
    "answer_synthesis": ["synthesize", "cite"],
}


@dataclass
class AgentToken:
    """Scoped auth token issued to a specialist agent."""

    agent_name: str
    role: str
    permissions: list[str]
    issued_at: float = field(default_factory=time.time)
    expires_at: float = 0.0  # 0 means default TTL applied at creation

    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "role": self.role,
            "permissions": self.permissions,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }


def create_agent_token(
    name: str,
    role: str,
    permissions: list[str] | None = None,
    ttl_seconds: float = 3600.0,
) -> AgentToken:
    """Create an auth token for a specialist agent.

    If *permissions* is ``None``, default permissions for the role are used.
    """
    now = time.time()
    perms = permissions if permissions is not None else ROLE_PERMISSIONS.get(role, [])
    return AgentToken(
        agent_name=name,
        role=role,
        permissions=list(perms),
        issued_at=now,
        expires_at=now + ttl_seconds,
    )


def verify_agent_token(token: AgentToken) -> bool:
    """Return True if the token is valid (not expired)."""
    return time.time() < token.expires_at


def check_permission(token: AgentToken, required: str) -> bool:
    """Return True if the token is valid *and* carries the required permission."""
    if not verify_agent_token(token):
        return False
    return required in token.permissions
