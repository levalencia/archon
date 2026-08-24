"""Live backend log stream via SSE.

Captures structlog output and streams to frontend in real-time.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from contextlib import suppress

import structlog
from fastapi import APIRouter
from starlette.responses import StreamingResponse

logger = structlog.get_logger()

router = APIRouter(prefix="/api/logs", tags=["logs"])

# Circular buffer of recent logs + subscriber queues
_log_buffer: deque[dict] = deque(maxlen=200)
_subscribers: list[asyncio.Queue] = []


class LogCapture:
    """Structlog processor that captures logs for streaming."""

    def __call__(self, logger_obj, method_name, event_dict):
        entry = {
            "ts": time.strftime("%H:%M:%S"),
            "level": method_name,
            "event": event_dict.get("event", ""),
            "data": {
                k: str(v)[:200]
                for k, v in event_dict.items()
                if k not in ("event", "timestamp", "_record", "_from_structlog")
            },
        }
        _log_buffer.append(entry)

        # Push to all subscribers
        for q in _subscribers[:]:
            with suppress(asyncio.QueueFull):
                q.put_nowait(entry)

        return event_dict


def install_log_capture():
    """Add LogCapture processor to structlog chain."""
    current = structlog.get_config().get("processors", [])
    # Insert our capture before the last processor (renderer)
    if not any(isinstance(p, LogCapture) for p in current):
        capture = LogCapture()
        new_processors = current[:-1] + [capture] + current[-1:]
        structlog.configure(processors=new_processors)
        logger.info("log_capture_installed")


@router.get("/stream")
async def stream_logs():
    """SSE endpoint for real-time backend logs."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers.append(queue)

    async def event_stream():
        try:
            # Send buffered logs first
            for entry in list(_log_buffer)[-50:]:
                yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"

            # Stream new logs
            while True:
                try:
                    entry = await asyncio.wait_for(queue.get(), timeout=5.0)
                    yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"
                except TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            if queue in _subscribers:
                _subscribers.remove(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/recent")
async def recent_logs(limit: int = 50):
    """Get recent logs (non-streaming)."""
    return list(_log_buffer)[-limit:]
