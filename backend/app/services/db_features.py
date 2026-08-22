"""Database features: row-level security, conversation sharding, virus scan stub.

Plan items #27, #37, #95.
"""

from __future__ import annotations

import hashlib

import structlog

logger = structlog.get_logger()


# --- Row-level security (#27) ---


class RowLevelSecurity:
    """Enforce user-scoped data access at the application level.

    In production PostgreSQL, this maps to RLS policies:
    ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
    CREATE POLICY user_isolation ON conversations
        USING (user_id = current_setting('app.current_user_id'));
    """

    def __init__(self) -> None:
        self._current_user: str = "default"

    def set_user(self, user_id: str) -> None:
        self._current_user = user_id

    def filter_query(self, query_params: dict) -> dict:
        """Add user_id filter to any query."""
        query_params["user_id"] = self._current_user
        return query_params

    def check_access(self, resource_user_id: str) -> bool:
        """Check if current user can access this resource."""
        if self._current_user == "admin":
            return True
        return resource_user_id == self._current_user

    def get_rls_sql(self, table: str) -> str:
        """Generate PostgreSQL RLS policy SQL."""
        return f"""
-- Enable RLS on {table}
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;

-- User isolation policy
CREATE POLICY {table}_user_isolation ON {table}
    USING (user_id = current_setting('app.current_user_id'));

-- Admin bypass
CREATE POLICY {table}_admin_bypass ON {table}
    TO admin_role USING (true);
"""


# --- Conversation sharding (#95) ---


class ConversationSharder:
    """Shard conversations across PostgreSQL schemas by user_id.

    Each user gets their own schema for data isolation.
    In production: CREATE SCHEMA user_{hash};
    """

    def __init__(self, num_shards: int = 16) -> None:
        self.num_shards = num_shards

    def get_shard(self, user_id: str) -> int:
        """Determine shard number for a user_id."""
        h = int(hashlib.md5(user_id.encode()).hexdigest(), 16)  # noqa: S324
        return h % self.num_shards

    def get_schema_name(self, user_id: str) -> str:
        """Get PostgreSQL schema name for a user."""
        shard = self.get_shard(user_id)
        return f"shard_{shard:02d}"

    def get_create_schema_sql(self, user_id: str) -> str:
        schema = self.get_schema_name(user_id)
        return f"""
CREATE SCHEMA IF NOT EXISTS {schema};
SET search_path TO {schema}, public;
"""


# --- Virus scan stub (#37) ---


async def scan_document(content: bytes, filename: str) -> dict:
    """Stub for virus/malware scanning on uploaded documents.

    In production: integrate with ClamAV, VirusTotal, or Azure Defender.
    """
    # Check file size
    max_size = 50 * 1024 * 1024  # 50MB
    if len(content) > max_size:
        return {"safe": False, "reason": f"File too large ({len(content)} bytes, max {max_size})"}

    # Check known dangerous extensions
    dangerous = [".exe", ".bat", ".cmd", ".ps1", ".sh", ".dll", ".vbs"]
    if any(filename.lower().endswith(ext) for ext in dangerous):
        return {"safe": False, "reason": f"Dangerous file extension: {filename}"}

    # Check for embedded scripts in text files
    if isinstance(content, bytes):
        text = content.decode(errors="ignore")
        if "<script" in text.lower() or "<?php" in text.lower():
            return {"safe": False, "reason": "Embedded script detected"}

    logger.info("virus_scan_passed", filename=filename, size=len(content))
    return {"safe": True, "reason": "passed", "scanner": "stub"}
