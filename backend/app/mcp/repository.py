"""Durable owner/project-scoped MCP configuration and safe tool inventory."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from app.mcp.models import ToolDescriptor
from app.services.db_store import MCPServerRow, MCPToolRow

_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_TOOL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]*$")
_UNSET = object()


class MCPHealth(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    ERROR = "error"
    DISABLED = "disabled"


def _identifier(value: str, label: str, maximum: int = 255) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    normalized = unicodedata.normalize("NFC", value)
    if not normalized or normalized != normalized.strip() or len(normalized) > maximum:
        raise ValueError(f"invalid {label}")
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise ValueError(f"invalid {label}")
    return normalized


def _uuid(value: str, label: str) -> str:
    value = _identifier(value, label, 36)
    try:
        parsed = uuid.UUID(value)
    except ValueError as error:
        raise ValueError(f"{label} must be a UUID") from error
    if str(parsed) != value:
        raise ValueError(f"{label} must be a canonical UUID")
    return value


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("timestamp must be a datetime")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _schema_json(schema: object) -> str:
    try:
        encoded = json.dumps(
            schema, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
        )
    except (TypeError, ValueError, UnicodeError) as error:
        raise ValueError("invalid tool schema") from error
    if len(encoded.encode("utf-8")) > 64_000:
        raise ValueError("tool schema is too large")
    return encoded


def _prepare_tool(tool: ToolDescriptor) -> tuple[ToolDescriptor, str]:
    if not isinstance(tool, ToolDescriptor):
        raise TypeError("inventory entries must be ToolDescriptor values")
    if not _TOOL_NAME.fullmatch(tool.name) or len(tool.name.encode("utf-8")) > 128:
        raise ValueError("invalid tool name")
    if tool.title is not None and (not isinstance(tool.title, str) or len(tool.title) > 500):
        raise ValueError("invalid tool title")
    if tool.description is not None and (
        not isinstance(tool.description, str) or len(tool.description) > 10_000
    ):
        raise ValueError("invalid tool description")
    if tool.version is not None and (not isinstance(tool.version, str) or len(tool.version) > 100):
        raise ValueError("invalid tool version")
    if type(tool.read_only) is not bool or type(tool.destructive) is not bool:
        raise ValueError("invalid tool safety metadata")
    if not isinstance(tool.input_schema, Mapping) or tool.input_schema.get("type") != "object":
        raise ValueError("invalid tool schema")
    return tool, _schema_json(tool.input_schema)


@dataclass(frozen=True, slots=True)
class MCPToolRecord:
    id: str
    server_id: str
    name: str
    title: str | None
    description: str | None
    input_schema: dict[str, Any]
    read_only: bool
    destructive: bool
    enabled: bool
    version: str | None


@dataclass(frozen=True, slots=True)
class MCPToolMetadataRecord:
    """Schema-free inventory row used to select tools before materialization."""

    id: str
    server_id: str
    name: str
    title: str | None
    description: str | None
    read_only: bool
    destructive: bool
    version: str | None
    schema_hash: str


@dataclass(frozen=True, slots=True)
class MCPServerRecord:
    id: str
    owner_id: str
    project_id: str
    name: str
    profile_id: str
    transport: str
    enabled: bool
    health: MCPHealth
    last_error_code: str | None
    last_seen: datetime | None
    created_at: datetime
    updated_at: datetime


class MCPRepository:
    """Async SQLAlchemy repository; every server lookup is scope-bound."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def create(
        self,
        *,
        owner_id: str,
        project_id: str,
        name: str,
        profile_id: str,
        enabled: bool = False,
        transport: str = "stdio",
        now: datetime | None = None,
    ) -> MCPServerRecord:
        current = _utc(now or datetime.now(tz=UTC))
        if transport not in {"stdio", "streamable_http"}:
            raise ValueError("invalid MCP transport")
        row = MCPServerRow(
            id=str(uuid.uuid4()),
            owner_id=_identifier(owner_id, "owner_id"),
            project_id=_identifier(project_id, "project_id"),
            name=_identifier(name, "name"),
            profile_id=_identifier(profile_id, "profile_id"),
            transport=transport,
            enabled=bool(enabled),
            health=MCPHealth.UNKNOWN.value if enabled else MCPHealth.DISABLED.value,
            last_error_code=None,
            last_seen=None,
            created_at=current,
            updated_at=current,
        )
        async with self._sessions() as session:
            session.add(row)
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise ValueError("duplicate MCP server name in owner/project scope") from error
        return self._server(row)

    async def get(
        self, *, owner_id: str, project_id: str, server_id: str
    ) -> MCPServerRecord | None:
        scope = self._scope(owner_id, project_id, server_id)
        async with self._sessions() as session:
            row = (await session.execute(select(MCPServerRow).where(*scope))).scalar_one_or_none()
            return None if row is None else self._server(row)

    async def list(self, *, owner_id: str, project_id: str) -> tuple[MCPServerRecord, ...]:
        owner = _identifier(owner_id, "owner_id")
        project = _identifier(project_id, "project_id")
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(MCPServerRow)
                    .where(MCPServerRow.owner_id == owner, MCPServerRow.project_id == project)
                    .order_by(MCPServerRow.name, MCPServerRow.id)
                )
            ).scalars()
            return tuple(self._server(row) for row in rows)

    async def update(
        self,
        *,
        owner_id: str,
        project_id: str,
        server_id: str,
        name: str | None = None,
        profile_id: str | None = None,
        enabled: bool | None = None,
        transport: str | None = None,
        now: datetime | None = None,
    ) -> MCPServerRecord | None:
        values: dict[str, object] = {"updated_at": _utc(now or datetime.now(tz=UTC))}
        if name is not None:
            values["name"] = _identifier(name, "name")
        requested_profile = None if profile_id is None else _identifier(profile_id, "profile_id")
        if transport is not None and transport not in {"stdio", "streamable_http"}:
            raise ValueError("invalid MCP transport")
        if enabled is not None:
            values["enabled"] = bool(enabled)
            values["health"] = MCPHealth.UNKNOWN.value if enabled else MCPHealth.DISABLED.value
            values["last_error_code"] = None
        scope = self._scope(owner_id, project_id, server_id)
        async with self._sessions() as session:
            try:
                locked = await session.execute(
                    update(MCPServerRow).where(*scope).values(updated_at=MCPServerRow.updated_at)
                )
                if locked.rowcount != 1:
                    await session.rollback()
                    return None
                row = (
                    await session.execute(select(MCPServerRow).where(*scope).with_for_update())
                ).scalar_one()
                profile_changed = (
                    requested_profile is not None and requested_profile != row.profile_id
                )
                transport_changed = transport is not None and transport != row.transport
                if requested_profile is not None:
                    values["profile_id"] = requested_profile
                if transport is not None:
                    values["transport"] = transport
                if profile_changed or transport_changed:
                    final_enabled = bool(values.get("enabled", row.enabled))
                    values["health"] = (
                        MCPHealth.UNKNOWN.value if final_enabled else MCPHealth.DISABLED.value
                    )
                    values["last_error_code"] = None
                    values["last_seen"] = None
                    await session.execute(
                        delete(MCPToolRow).where(MCPToolRow.server_id == server_id)
                    )
                for key, value in values.items():
                    setattr(row, key, value)
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise ValueError("duplicate MCP server name in owner/project scope") from error
            return self._server(row)

    async def delete(self, *, owner_id: str, project_id: str, server_id: str) -> bool:
        scope = self._scope(owner_id, project_id, server_id)
        async with self._sessions() as session:
            row = (
                await session.execute(select(MCPServerRow.id).where(*scope))
            ).scalar_one_or_none()
            if row is None:
                return False
            await session.execute(delete(MCPServerRow).where(*scope))
            await session.commit()
            return True

    async def list_tools(
        self,
        *,
        owner_id: str,
        project_id: str,
        server_id: str,
        enabled_only: bool = False,
        excluded_tool_ids: frozenset[str] = frozenset(),
    ) -> tuple[MCPToolRecord, ...]:
        scope = self._scope(owner_id, project_id, server_id)
        excluded = tuple(_uuid(value, "excluded_tool_id") for value in excluded_tool_ids)
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(MCPToolRow)
                    .join(MCPServerRow, MCPServerRow.id == MCPToolRow.server_id)
                    .where(
                        *scope,
                        *([MCPToolRow.enabled.is_(True)] if enabled_only else []),
                        *([MCPToolRow.id.not_in(excluded)] if excluded else []),
                    )
                    .order_by(MCPToolRow.name)
                )
            ).scalars()
            return tuple(self._tool(row) for row in rows)

    async def list_tool_metadata(
        self,
        *,
        owner_id: str,
        project_id: str,
        server_id: str,
        enabled_only: bool = False,
        excluded_tool_ids: frozenset[str] = frozenset(),
    ) -> tuple[MCPToolMetadataRecord, ...]:
        """List compact tool metadata without decoding any persisted schema JSON."""
        scope = self._scope(owner_id, project_id, server_id)
        excluded = tuple(_uuid(value, "excluded_tool_id") for value in excluded_tool_ids)
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(
                        MCPToolRow.id,
                        MCPToolRow.server_id,
                        MCPToolRow.name,
                        MCPToolRow.title,
                        MCPToolRow.description,
                        MCPToolRow.read_only,
                        MCPToolRow.destructive,
                        MCPToolRow.version,
                        MCPToolRow.input_schema_json,
                    )
                    .join(MCPServerRow, MCPServerRow.id == MCPToolRow.server_id)
                    .where(
                        *scope,
                        *([MCPToolRow.enabled.is_(True)] if enabled_only else []),
                        *([MCPToolRow.id.not_in(excluded)] if excluded else []),
                    )
                    .order_by(MCPToolRow.name, MCPToolRow.id)
                )
            ).all()
        return tuple(
            MCPToolMetadataRecord(
                id=row.id,
                server_id=row.server_id,
                name=row.name,
                title=row.title,
                description=row.description,
                read_only=bool(row.read_only),
                destructive=bool(row.destructive),
                version=row.version,
                schema_hash=hashlib.sha256(row.input_schema_json.encode("utf-8")).hexdigest(),
            )
            for row in rows
        )

    async def load_tools(
        self,
        *,
        owner_id: str,
        project_id: str,
        server_id: str,
        tool_ids: frozenset[str],
    ) -> tuple[MCPToolRecord, ...]:
        """Decode schemas only for explicitly selected tool IDs."""
        if not tool_ids:
            return ()
        selected = tuple(_uuid(value, "tool_id") for value in tool_ids)
        scope = self._scope(owner_id, project_id, server_id)
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(MCPToolRow)
                    .join(MCPServerRow, MCPServerRow.id == MCPToolRow.server_id)
                    .where(*scope, MCPToolRow.id.in_(selected))
                    .order_by(MCPToolRow.name, MCPToolRow.id)
                )
            ).scalars()
            return tuple(self._tool(row) for row in rows)

    async def replace_inventory(
        self,
        *,
        owner_id: str,
        project_id: str,
        server_id: str,
        tools: tuple[ToolDescriptor, ...],
        expected_profile_id: str | None = None,
    ) -> tuple[MCPToolRecord, ...]:
        scope = self._scope(owner_id, project_id, server_id)
        prepared = [_prepare_tool(tool) for tool in tools]
        names = [tool.name for tool, _schema in prepared]
        if len(set(names)) != len(names):
            raise ValueError("duplicate tool name")
        expected_profile = (
            None
            if expected_profile_id is None
            else _identifier(expected_profile_id, "expected_profile_id")
        )
        async with self._sessions() as session:
            if expected_profile is not None:
                locked = await session.execute(
                    update(MCPServerRow)
                    .where(*scope, MCPServerRow.profile_id == expected_profile)
                    .values(updated_at=MCPServerRow.updated_at)
                )
                if locked.rowcount != 1:
                    await session.rollback()
                    raise LookupError("MCP server profile changed")
            server = (
                await session.execute(select(MCPServerRow).where(*scope).with_for_update())
            ).scalar_one_or_none()
            if server is None:
                raise LookupError("MCP server not found")
            if expected_profile is not None and server.profile_id != expected_profile:
                raise LookupError("MCP server profile changed")
            old_rows = (
                await session.execute(select(MCPToolRow).where(MCPToolRow.server_id == server_id))
            ).scalars()
            old = {row.name: row for row in old_rows}
            await session.execute(delete(MCPToolRow).where(MCPToolRow.server_id == server_id))
            rows: list[MCPToolRow] = []
            for tool, schema_json in prepared:
                previous = old.get(tool.name)
                row = MCPToolRow(
                    id=str(uuid.uuid4()),
                    server_id=server_id,
                    name=tool.name,
                    title=tool.title,
                    description=tool.description,
                    input_schema_json=schema_json,
                    read_only=tool.read_only,
                    destructive=tool.destructive,
                    enabled=bool(
                        previous is not None
                        and previous.enabled
                        and previous.input_schema_json == schema_json
                    ),
                    version=tool.version,
                )
                session.add(row)
                rows.append(row)
            await session.commit()
            return tuple(self._tool(row) for row in sorted(rows, key=lambda item: item.name))

    async def update_health(
        self,
        *,
        owner_id: str,
        project_id: str,
        server_id: str,
        health: MCPHealth,
        error_code: str | None = None,
        last_seen: datetime | None | object = _UNSET,
        now: datetime | None = None,
        expected_profile_id: str | None = None,
    ) -> bool:
        state = MCPHealth(health)
        if error_code is not None and not _ERROR_CODE.fullmatch(error_code):
            raise ValueError("unsafe MCP error code")
        if state is MCPHealth.ERROR and error_code is None:
            raise ValueError("error health requires an error code")
        if state is not MCPHealth.ERROR and error_code is not None:
            raise ValueError("error code is only valid for error health")
        values: dict[str, object] = {
            "health": state.value,
            "last_error_code": error_code,
            "updated_at": _utc(now or datetime.now(tz=UTC)),
        }
        if last_seen is not _UNSET:
            values["last_seen"] = None if last_seen is None else _utc(last_seen)  # type: ignore[arg-type]
        scope = self._scope(owner_id, project_id, server_id)
        if expected_profile_id is not None:
            scope = (
                *scope,
                MCPServerRow.profile_id == _identifier(expected_profile_id, "expected_profile_id"),
            )
        async with self._sessions() as session:
            result = await session.execute(update(MCPServerRow).where(*scope).values(**values))
            await session.commit()
            return bool(result.rowcount == 1)

    async def disable_tool(
        self,
        *,
        owner_id: str,
        project_id: str,
        server_id: str,
        tool_id: str,
    ) -> bool:
        """Fail closed without decoding a potentially malformed persisted schema."""
        scope = self._scope(owner_id, project_id, server_id)
        async with self._sessions() as session:
            server = (
                await session.execute(select(MCPServerRow.id).where(*scope))
            ).scalar_one_or_none()
            if server is None:
                return False
            result = await session.execute(
                update(MCPToolRow)
                .where(
                    MCPToolRow.server_id == server_id, MCPToolRow.id == _uuid(tool_id, "tool_id")
                )
                .values(enabled=False)
            )
            await session.commit()
            return bool(result.rowcount == 1)

    async def set_tool_enabled(
        self,
        *,
        owner_id: str,
        project_id: str,
        server_id: str,
        enabled: bool,
        tool_id: str | None = None,
        name: str | None = None,
    ) -> MCPToolRecord | None:
        if (tool_id is None) == (name is None):
            raise ValueError("provide exactly one of tool_id or name")
        scope = self._scope(owner_id, project_id, server_id)
        tool_filter = (
            MCPToolRow.id == _uuid(tool_id, "tool_id")
            if tool_id is not None
            else MCPToolRow.name == _identifier(name or "", "tool name", 128)
        )
        async with self._sessions() as session:
            server = (
                await session.execute(select(MCPServerRow.id).where(*scope))
            ).scalar_one_or_none()
            if server is None:
                return None
            await session.execute(
                update(MCPToolRow)
                .where(MCPToolRow.server_id == server_id, tool_filter)
                .values(enabled=bool(enabled))
            )
            row = (
                await session.execute(
                    select(MCPToolRow).where(MCPToolRow.server_id == server_id, tool_filter)
                )
            ).scalar_one_or_none()
            await session.commit()
            return None if row is None else self._tool(row)

    @staticmethod
    def _scope(owner_id: str, project_id: str, server_id: str) -> tuple[ColumnElement[bool], ...]:
        return (
            MCPServerRow.owner_id == _identifier(owner_id, "owner_id"),
            MCPServerRow.project_id == _identifier(project_id, "project_id"),
            MCPServerRow.id == _uuid(server_id, "server_id"),
        )

    @staticmethod
    def _server(row: MCPServerRow) -> MCPServerRecord:
        return MCPServerRecord(
            id=row.id,
            owner_id=row.owner_id,
            project_id=row.project_id,
            name=row.name,
            profile_id=row.profile_id,
            transport=row.transport,
            enabled=bool(row.enabled),
            health=MCPHealth(row.health),
            last_error_code=row.last_error_code,
            last_seen=None if row.last_seen is None else _utc(row.last_seen),
            created_at=_utc(row.created_at),
            updated_at=_utc(row.updated_at),
        )

    @staticmethod
    def _tool(row: MCPToolRow) -> MCPToolRecord:
        schema = json.loads(row.input_schema_json)
        if not isinstance(schema, dict):
            raise ValueError("invalid persisted MCP tool schema")
        return MCPToolRecord(
            id=row.id,
            server_id=row.server_id,
            name=row.name,
            title=row.title,
            description=row.description,
            input_schema=schema,
            read_only=bool(row.read_only),
            destructive=bool(row.destructive),
            enabled=bool(row.enabled),
            version=row.version,
        )
