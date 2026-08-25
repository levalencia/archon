"""Background task API routes.

POST /api/tasks/submit  — Submit a background task (agent tool)
GET  /api/tasks/{id}    — Get task status/result
GET  /api/tasks         — List all tasks
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.task_queue import get_task_queue

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskSubmitRequest(BaseModel):
    command: str = ""
    description: str = ""


@router.post("/submit")
async def submit_task(body: TaskSubmitRequest) -> dict:
    """Submit a background task. Returns task_id."""
    queue = get_task_queue()

    async def _placeholder_task() -> dict:
        """Placeholder background work (simulates processing)."""
        await asyncio.sleep(0.1)
        return {"message": f"Task completed: {body.description or body.command}"}

    task_id = await queue.submit_task(_placeholder_task)
    return {"task_id": task_id, "status": "pending"}


@router.get("/{task_id}")
async def get_task_status(task_id: str) -> dict:
    """Get background task status and result."""
    queue = get_task_queue()
    status = queue.get_status(task_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return status


@router.get("")
async def list_tasks() -> dict:
    """List all background tasks."""
    queue = get_task_queue()
    return {"tasks": queue.list_tasks(), "count": len(queue.list_tasks())}
