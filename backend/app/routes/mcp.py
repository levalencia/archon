"""Authenticated, owner-scoped MCP server and discovered-tool administration."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.mcp.inventory import MCPInventoryError, MCPInventoryService
from app.mcp.repository import MCPRepository, MCPServerRecord, MCPToolRecord
from app.security.auth import get_current_user
from app.security.dependencies import enforce_rate_limit

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

_PROJECT_PATTERN = r"^[^\s\x00-\x1f\x7f](?:[^\x00-\x1f\x7f]{0,253}[^\s\x00-\x1f\x7f])?$"
_TOOL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]*$")
ProjectId = Annotated[str, Field(min_length=1, max_length=255, pattern=_PROJECT_PATTERN)]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ServerCreate(_StrictModel):
    project_id: ProjectId
    name: str = Field(min_length=1, max_length=255)
    profile_id: str = Field(min_length=1, max_length=255)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_identifiers(self) -> ServerCreate:
        _validate_text(self.name, "name")
        _validate_text(self.profile_id, "profile_id")
        return self


class ServerUpdate(_StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    profile_id: str | None = Field(default=None, min_length=1, max_length=255)
    enabled: bool | None = None

    @model_validator(mode="after")
    def validate_update(self) -> ServerUpdate:
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        for field_name in self.model_fields_set:
            value = getattr(self, field_name)
            if value is None:
                raise ValueError(f"{field_name} may not be null")
            if isinstance(value, str):
                _validate_text(value, field_name)
        return self


class ToolUpdate(_StrictModel):
    enabled: bool


class ServerResponse(_StrictModel):
    id: str
    project_id: str
    name: str
    profile_id: str
    transport: str
    enabled: bool
    health: str
    last_error_code: str | None
    last_seen: datetime | None
    created_at: datetime
    updated_at: datetime


class ToolResponse(_StrictModel):
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


def _validate_text(value: str, label: str) -> None:
    contains_control = any(ord(character) < 32 or ord(character) == 127 for character in value)
    if value != value.strip() or contains_control:
        raise ValueError(f"invalid {label}")


def _repository(request: Request) -> MCPRepository:
    return cast(MCPRepository, request.app.state.mcp_repository)


def _inventory(request: Request) -> MCPInventoryService:
    return cast(MCPInventoryService, request.app.state.mcp_inventory)


def _server_response(record: MCPServerRecord) -> ServerResponse:
    return ServerResponse(
        id=record.id,
        project_id=record.project_id,
        name=record.name,
        profile_id=record.profile_id,
        transport=record.transport,
        enabled=record.enabled,
        health=record.health.value,
        last_error_code=record.last_error_code,
        last_seen=record.last_seen,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _tool_response(record: MCPToolRecord) -> ToolResponse:
    return ToolResponse(
        id=record.id,
        server_id=record.server_id,
        name=record.name,
        title=record.title,
        description=record.description,
        input_schema=record.input_schema,
        read_only=record.read_only,
        destructive=record.destructive,
        enabled=record.enabled,
        version=record.version,
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "server_not_found"})


async def _limit(request: Request, user: dict[str, Any], action: str) -> None:
    await enforce_rate_limit(request, user, f"mcp_{action}")


@router.get("/profiles", response_model=list[dict[str, str]])
async def list_profiles(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> list[dict[str, str]]:
    """Expose safe labels only, never command, arguments, environment, or secrets."""
    await enforce_rate_limit(request, user, "mcp_read")
    return [
        {
            "id": profile_id,
            "display_name": profile_id.replace("_", " ").replace("-", " ").title(),
        }
        for profile_id in sorted(request.app.state.mcp_profiles)
    ]


@router.post("/servers", response_model=ServerResponse, status_code=status.HTTP_201_CREATED)
async def create_server(
    body: ServerCreate,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> ServerResponse:
    await _limit(request, user, "write")
    try:
        record = await _inventory(request).create_server(
            owner_id=user["user_id"],
            project_id=body.project_id,
            name=body.name,
            profile_id=body.profile_id,
            enabled=body.enabled,
        )
    except MCPInventoryError as error:
        raise HTTPException(status_code=422, detail={"code": error.code}) from None
    except ValueError as error:
        raise HTTPException(status_code=409, detail={"code": "server_name_conflict"}) from error
    return _server_response(record)


@router.get("/servers", response_model=list[ServerResponse])
async def list_servers(
    request: Request,
    project_id: Annotated[ProjectId, Query()],
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> list[ServerResponse]:
    await _limit(request, user, "read")
    records = await _repository(request).list(owner_id=user["user_id"], project_id=project_id)
    return [_server_response(record) for record in records]


@router.get("/servers/{server_id}", response_model=ServerResponse)
async def get_server(
    server_id: str,
    request: Request,
    project_id: Annotated[ProjectId, Query()],
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> ServerResponse:
    await _limit(request, user, "read")
    try:
        record = await _repository(request).get(
            owner_id=user["user_id"], project_id=project_id, server_id=server_id
        )
    except ValueError:
        record = None
    if record is None:
        raise _not_found()
    return _server_response(record)


@router.patch("/servers/{server_id}", response_model=ServerResponse)
async def update_server(
    server_id: str,
    body: ServerUpdate,
    request: Request,
    project_id: Annotated[ProjectId, Query()],
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> ServerResponse:
    await _limit(request, user, "write")
    fields = body.model_fields_set
    try:
        record = await _inventory(request).update_server(
            owner_id=user["user_id"],
            project_id=project_id,
            server_id=server_id,
            name=body.name if "name" in fields else None,
            profile_id=body.profile_id if "profile_id" in fields else None,
            enabled=body.enabled if "enabled" in fields else None,
        )
    except MCPInventoryError as error:
        raise HTTPException(status_code=422, detail={"code": error.code}) from None
    except ValueError as error:
        if "duplicate" in str(error):
            raise HTTPException(status_code=409, detail={"code": "server_name_conflict"}) from error
        record = None
    if record is None:
        raise _not_found()
    return _server_response(record)


@router.delete("/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server(
    server_id: str,
    request: Request,
    project_id: Annotated[ProjectId, Query()],
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> None:
    await _limit(request, user, "write")
    try:
        deleted = await _repository(request).delete(
            owner_id=user["user_id"], project_id=project_id, server_id=server_id
        )
    except ValueError:
        deleted = False
    if not deleted:
        raise _not_found()


@router.post("/servers/{server_id}/discover", response_model=list[ToolResponse])
async def discover_server(
    server_id: str,
    request: Request,
    project_id: Annotated[ProjectId, Query()],
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> list[ToolResponse]:
    await _limit(request, user, "discover")
    try:
        records = await _inventory(request).discover(
            owner_id=user["user_id"], project_id=project_id, server_id=server_id
        )
    except (MCPInventoryError, ValueError) as error:
        code = error.code if isinstance(error, MCPInventoryError) else "server_not_found"
        if code == "server_not_found":
            raise _not_found() from None
        if code == "unknown_profile":
            raise HTTPException(status_code=422, detail={"code": code}) from None
        raise HTTPException(status_code=503, detail={"code": code}) from None
    return [_tool_response(record) for record in records]


@router.get("/servers/{server_id}/tools", response_model=list[ToolResponse])
async def list_server_tools(
    server_id: str,
    request: Request,
    project_id: Annotated[ProjectId, Query()],
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> list[ToolResponse]:
    await _limit(request, user, "read")
    try:
        server = await _repository(request).get(
            owner_id=user["user_id"], project_id=project_id, server_id=server_id
        )
        if server is None:
            raise _not_found()
        records = await _repository(request).list_tools(
            owner_id=user["user_id"], project_id=project_id, server_id=server_id
        )
    except ValueError:
        raise _not_found() from None
    return [_tool_response(record) for record in records]


@router.patch("/servers/{server_id}/tools/{tool_name}", response_model=ToolResponse)
async def update_server_tool(
    server_id: str,
    tool_name: str,
    body: ToolUpdate,
    request: Request,
    project_id: Annotated[ProjectId, Query()],
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> ToolResponse:
    await _limit(request, user, "write")
    if len(tool_name.encode("utf-8")) > 128 or not _TOOL_PATTERN.fullmatch(tool_name):
        raise HTTPException(status_code=404, detail={"code": "tool_not_found"})
    try:
        record = await _repository(request).set_tool_enabled(
            owner_id=user["user_id"],
            project_id=project_id,
            server_id=server_id,
            name=tool_name,
            enabled=body.enabled,
        )
    except ValueError:
        record = None
    if record is None:
        raise HTTPException(status_code=404, detail={"code": "tool_not_found"})
    return _tool_response(record)


_LEGACY_GUIDANCE = (
    "MCP execution is no longer exposed here; use the governed server inventory APIs."
)


@router.post("/request", status_code=status.HTTP_410_GONE)
async def deprecated_request(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> None:
    await _limit(request, user, "write")
    raise HTTPException(status_code=410, detail=_LEGACY_GUIDANCE)


@router.get("/tools", status_code=status.HTTP_410_GONE)
async def deprecated_tools(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> None:
    await _limit(request, user, "read")
    raise HTTPException(status_code=410, detail=_LEGACY_GUIDANCE)
