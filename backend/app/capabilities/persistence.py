"""Durable project capability preferences."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.db_store import ProjectCapabilityPreferenceRow, ProjectWorkspaceRow


class CapabilityPreferenceRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def set(
        self, *, owner_id: str, project_id: str, capability_id: str, enabled: bool, pinned: bool
    ) -> ProjectCapabilityPreferenceRow:
        now = datetime.now(tz=UTC)
        async with self._sessions() as session, session.begin():
            workspace = await session.get(ProjectWorkspaceRow, (owner_id, project_id))
            if workspace is None:
                session.add(
                    ProjectWorkspaceRow(
                        owner_id=owner_id, project_id=project_id, created_at=now, updated_at=now
                    )
                )
            row = await session.get(
                ProjectCapabilityPreferenceRow, (owner_id, project_id, capability_id)
            )
            if row is None:
                row = ProjectCapabilityPreferenceRow(
                    owner_id=owner_id,
                    project_id=project_id,
                    capability_id=capability_id,
                    enabled=enabled,
                    pinned=pinned,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            else:
                row.enabled, row.pinned, row.updated_at = enabled, pinned, now
            await session.flush()
            return row

    async def list(self, *, owner_id: str, project_id: str) -> list[ProjectCapabilityPreferenceRow]:
        async with self._sessions() as session:
            return list(
                await session.scalars(
                    select(ProjectCapabilityPreferenceRow)
                    .where(
                        ProjectCapabilityPreferenceRow.owner_id == owner_id,
                        ProjectCapabilityPreferenceRow.project_id == project_id,
                    )
                    .order_by(ProjectCapabilityPreferenceRow.capability_id)
                )
            )
