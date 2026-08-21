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

import structlog

logger = structlog.get_logger()


class StructuredAuditLogger:
    """SQLite-backed audit logger. Satisfies the AuditLog Protocol.

    Uses check_same_thread=False for async safety.
    Production would use PostgreSQL; SQLite is for local dev and tests.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
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
        self._conn.execute(
            """INSERT INTO audit_log
               (timestamp, agent_id, action, resource, parameters, result, security_level, correlation_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                time.time(),
                agent_id,
                action,
                resource,
                json.dumps(parameters) if parameters else None,
                result,
                security_level,
                correlation_id,
            ),
        )
        self._conn.commit()

        logger.info(
            "audit_entry",
            agent_id=agent_id,
            action=action,
            resource=resource,
            result=result,
            security_level=security_level,
            correlation_id=correlation_id,
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
        conditions = []
        params: list = []

        if agent_id:
            conditions.append("agent_id = ?")
            params.append(agent_id)
        if action:
            conditions.append("action = ?")
            params.append(action)
        if correlation_id:
            conditions.append("correlation_id = ?")
            params.append(correlation_id)
        if security_level:
            conditions.append("security_level = ?")
            params.append(security_level)

        where = " AND ".join(conditions) if conditions else "1=1"
        cursor = self._conn.execute(
            f"SELECT * FROM audit_log WHERE {where} ORDER BY timestamp DESC",  # noqa: S608
            params,
        )
        return [dict(row) for row in cursor.fetchall()]

    async def count_by_action(self) -> dict[str, int]:
        """Count entries grouped by action."""
        cursor = self._conn.execute(
            "SELECT action, COUNT(*) as count FROM audit_log GROUP BY action"
        )
        return {row["action"]: row["count"] for row in cursor.fetchall()}
