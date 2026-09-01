# ruff: noqa: B008
"""Search and effective project capability API."""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.capabilities.index import CapabilityIndex
from app.capabilities.models import CapabilityDescriptor
from app.capabilities.persistence import CapabilityPreferenceRepository
from app.capabilities.selector import SelectionRequest, select_capabilities
from app.security.auth import get_current_user
from app.security.dependencies import enforce_rate_limit

router = APIRouter(prefix="/api/capabilities", tags=["capabilities"])
ProjectId = Annotated[
    str, Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CapabilityItem(StrictModel):
    id: str
    name: str
    description: str
    kind: str
    source: str
    version: str
    trust_state: str
    enabled: bool
    pinned: bool
    risk_classes: list[str]


class SearchBody(StrictModel):
    query: str = Field(min_length=1, max_length=500)
    project_id: ProjectId | None = None
    limit: int = Field(default=20, ge=1, le=100)


class PreferenceBody(StrictModel):
    enabled: bool = True
    pinned: bool = False


class EffectiveBody(StrictModel):
    intent: str = Field(default="", max_length=2000)
    current_path: str | None = Field(default=None, max_length=1000)
    context_budget: int = Field(default=100000, ge=0, le=10000000)


def _prefs(request: Request) -> CapabilityPreferenceRepository:
    return cast(CapabilityPreferenceRepository, request.app.state.capability_preferences)


def _index(request: Request) -> CapabilityIndex:
    return cast(CapabilityIndex, request.app.state.capability_index)


async def _limit(request: Request, user: dict[str, Any], action: str) -> None:
    await enforce_rate_limit(request, user, f"capabilities_{action}")


async def _scoped_index(request: Request, owner_id: str, project_id: str | None) -> CapabilityIndex:
    descriptors = list(_index(request).all())
    if project_id is not None:
        metadata = await request.app.state.mcp_runtime_tools.metadata_for_scope(
            owner_id, project_id
        )
        descriptors.extend(
            CapabilityDescriptor(
                id=item.capability_id,
                kind="mcp",
                name=item.name,
                executable_name=item.name,
                description=item.description,
                tags=tuple(
                    sorted(
                        {
                            "network",
                            "read" if item.read_only else "write",
                            *(
                                {"external_side_effect"}
                                if not item.read_only or item.destructive
                                else set()
                            ),
                        }
                    )
                ),
                context_cost=0,
                version=item.version,
                content_hash=item.schema_hash,
            )
            for item in metadata
        )
    return CapabilityIndex(descriptors)


def _item(d: CapabilityDescriptor, enabled: bool = True, pinned: bool = False) -> CapabilityItem:
    risks = sorted(set(d.required_permissions)) or ["read"]
    return CapabilityItem(
        id=d.id,
        name=d.name,
        description=d.description,
        kind=str(d.kind),
        source="builtin" if str(d.kind) == "native" else str(d.kind),
        version=d.version or "unversioned",
        trust_state="verified",
        enabled=enabled,
        pinned=pinned,
        risk_classes=risks,
    )


@router.post("/search", response_model=list[CapabilityItem])
async def search(
    body: SearchBody, request: Request, user: dict[str, Any] = Depends(get_current_user)
) -> list[CapabilityItem]:
    await _limit(request, user, "search")
    prefs = (
        {}
        if body.project_id is None
        else {
            x.capability_id: x
            for x in await _prefs(request).list(
                owner_id=user["user_id"], project_id=body.project_id
            )
        }
    )
    result = []
    q = body.query.casefold()
    for d in (await _scoped_index(request, user["user_id"], body.project_id)).all():
        if q in f"{d.id} {d.name} {d.description} {' '.join(d.tags)}".casefold():
            pref = prefs.get(d.id)
            result.append(
                _item(d, pref.enabled if pref else d.enabled, pref.pinned if pref else False)
            )
    return result[: body.limit]


@router.put("/projects/{project_id}/{capability_id}", response_model=CapabilityItem)
async def preference(
    project_id: ProjectId,
    capability_id: str,
    body: PreferenceBody,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> CapabilityItem:
    await _limit(request, user, "write")
    descriptor = (await _scoped_index(request, user["user_id"], project_id)).get(capability_id)
    if descriptor is None:
        raise HTTPException(404, detail={"code": "capability_not_found"})
    row = await _prefs(request).set(
        owner_id=user["user_id"],
        project_id=project_id,
        capability_id=capability_id,
        enabled=body.enabled,
        pinned=body.pinned,
    )
    return _item(descriptor, row.enabled, row.pinned)


@router.post("/projects/{project_id}/effective", response_model=dict[str, Any])
async def effective(
    project_id: ProjectId,
    body: EffectiveBody,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    await _limit(request, user, "read")
    prefs = {
        x.capability_id: x
        for x in await _prefs(request).list(owner_id=user["user_id"], project_id=project_id)
    }
    from dataclasses import replace

    descriptors = [
        replace(d, enabled=prefs[d.id].enabled if d.id in prefs else d.enabled)
        for d in (await _scoped_index(request, user["user_id"], project_id)).all()
    ]
    pinned = frozenset(k for k, v in prefs.items() if v.pinned and v.enabled)
    selected = select_capabilities(
        CapabilityIndex(descriptors),
        SelectionRequest(
            intent=body.intent,
            pinned_ids=pinned,
            current_path=body.current_path,
            context_budget=body.context_budget,
        ),
    )
    items = [_item(x.descriptor, True, x.descriptor.id in pinned) for x in selected.selected]
    return {
        "project_id": project_id,
        "items": items,
        "omitted": [x.descriptor.id for x in selected.rejected],
        "hidden": list(selected.hidden_ids),
        "summary": {
            "enabled": len(items),
            "pinned": sum(x.pinned for x in items),
            "context_cost_bytes": selected.context_cost,
        },
    }
