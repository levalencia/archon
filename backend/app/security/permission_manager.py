"""Permission manager with Path.resolve() and trailing slash security.

Fixes the sibling-prefix bypass bug found in AIAMastery Day 3:
- "/tmp/user/documents-evil" would match "/tmp/user/documents" with naive startswith
- Fix: append "/" before startswith check AND use Path.resolve() for symlink resolution

See: https://github.com/levalencia/production-ai-agents/articles/day-01-anatomy-of-production-agent/
Concept: Layer 5 - Guardrails (path validation, action allowlists)
"""

from __future__ import annotations

from pathlib import Path

import structlog

from app.observability.logging import get_correlation_id, safe_value_metadata

logger = structlog.get_logger()


class SecurePermissionManager:
    """Permission checker with Path.resolve() for all path operations.

    Satisfies the PermissionChecker Protocol.
    """

    def __init__(
        self,
        base_dir: Path | str | None = None,
        allowed_actions: set[str] | None = None,
    ) -> None:
        self._base_dir = Path(base_dir).resolve() if base_dir else None
        self._allowed_actions = allowed_actions or {
            "read_file",
            "write_file",
            "list_directory",
            "search",
            "calculate",
        }

    async def check(self, agent_id: str, resource: str, action: str, **kwargs: object) -> bool:
        """Check if an agent is allowed to perform an action.

        For file operations, validates the path is within base_dir.
        For other operations, checks the action allowlist.
        """
        correlation_id = get_correlation_id()

        # Check action is allowed
        if action not in self._allowed_actions:
            logger.warning(
                "permission_denied",
                agent_id=agent_id,
                resource=resource,
                action=action,
                reason="action_not_allowed",
                correlation_id=correlation_id,
            )
            return False

        # For file operations, check path is within base_dir
        if self._base_dir and action in {"read_file", "write_file", "list_directory"}:
            # Check 'path' in kwargs or use resource as path
            file_path_str = str(kwargs.get("path", resource))
            try:
                resolved = Path(file_path_str).resolve()
            except (ValueError, OSError):
                logger.warning(
                    "permission_denied",
                    agent_id=agent_id,
                    **safe_value_metadata("resource", file_path_str),
                    action=action,
                    reason="invalid_path",
                    correlation_id=correlation_id,
                )
                return False

            # THE CRITICAL FIX: append "/" to base_dir before startswith
            # Without this, "/tmp/user/documents-evil" matches "/tmp/user/documents"
            base_prefix = str(self._base_dir) + "/"

            if not (str(resolved) + "/").startswith(base_prefix) and resolved != self._base_dir:
                logger.warning(
                    "permission_denied",
                    agent_id=agent_id,
                    **safe_value_metadata("resource", str(resolved)),
                    action=action,
                    reason="outside_base_dir",
                    base_dir_configured=True,
                    correlation_id=correlation_id,
                )
                return False

        logger.info(
            "permission_granted",
            agent_id=agent_id,
            resource=resource,
            action=action,
            correlation_id=correlation_id,
        )
        return True
