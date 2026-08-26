"""Structured audit logger with SQLite storage and correlation IDs.

Every action in the system is logged with:
- timestamp, agent_id, action, resource, parameters, result
- security_level (info, warning, error)
- correlation_id (links all entries for a single request)

See: https://github.com/levalencia/production-ai-agents/articles/day-01-anatomy-of-production-agent/
Concept: Layer 6 - Observability (audit trails with correlation IDs)
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid

import structlog

from app.security.persistence_redactor import PersistenceRedactor

logger = structlog.get_logger()


class StructuredAuditLogger:
    """SQLite-backed audit logger. Satisfies the AuditLog Protocol.

    Uses check_same_thread=False for async safety.
    Production would use PostgreSQL; SQLite is for local dev and tests.
    """

    def __init__(self, redactor: PersistenceRedactor, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._redactor = redactor
        self._conn.row_factory = sqlite3.Row
        self._create_table()

    def _create_table(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                agent_id TEXT NOT NULL,
                action TEXT NOT NULL,
                resource TEXT NOT NULL,
                parameters TEXT,
                result TEXT NOT NULL DEFAULT 'success',
                security_level TEXT NOT NULL DEFAULT 'info',
                correlation_id TEXT
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_correlation ON audit_log(correlation_id)"
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_agent ON audit_log(agent_id)")
        self._conn.commit()

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
        safe_agent_id = self._redactor.redact_text(agent_id).text
        safe_action = self._redactor.redact_text(action).text
        safe_resource = self._redactor.redact_text(resource).text
        safe_result = self._redactor.redact_text(result).text
        safe_security_level = (
            security_level if security_level in {"info", "warning", "error"} else "warning"
        )
        safe_correlation_id: str | None = None
        if correlation_id is not None:
            try:
                safe_correlation_id = str(uuid.UUID(correlation_id))
            except (ValueError, AttributeError, TypeError):
                # Untrusted metadata is neither persisted nor emitted to structured logs.
                safe_correlation_id = None
        self._conn.execute(
            """INSERT INTO audit_log
               (timestamp, agent_id, action, resource,
                parameters, result, security_level, correlation_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                time.time(),
                safe_agent_id,
                safe_action,
                safe_resource,
                json.dumps(self._redactor.redact_value(parameters)) if parameters else None,
                safe_result,
                safe_security_level,
                safe_correlation_id,
            ),
        )
        self._conn.commit()

        logger.info(
            "audit_entry",
            agent_id=safe_agent_id,
            action=safe_action,
            resource=safe_resource,
            result=safe_result,
            security_level=safe_security_level,
            correlation_id=safe_correlation_id,
        )

    async def get_recent(self, limit: int = 100) -> list[dict]:
        """Get recent audit entries."""
        cursor = self._conn.execute(
            "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    async def search(
        self,
        agent_id: str | None = None,
        action: str | None = None,
        correlation_id: str | None = None,
        security_level: str | None = None,
    ) -> list[dict]:
        """Search audit entries by filters."""
        filter_values = (agent_id, action, correlation_id, security_level)
        filters = tuple(value or None for value in filter_values)
        cursor = self._conn.execute(
            """SELECT * FROM audit_log
               WHERE (? IS NULL OR agent_id = ?)
                 AND (? IS NULL OR action = ?)
                 AND (? IS NULL OR correlation_id = ?)
                 AND (? IS NULL OR security_level = ?)
               ORDER BY timestamp DESC""",
            tuple(value for filter_value in filters for value in (filter_value, filter_value)),
        )
        return [dict(row) for row in cursor.fetchall()]

    async def count_by_action(self) -> dict[str, int]:
        """Count entries grouped by action."""
        cursor = self._conn.execute(
            "SELECT action, COUNT(*) as count FROM audit_log GROUP BY action"
        )
        return {row["action"]: row["count"] for row in cursor.fetchall()}
