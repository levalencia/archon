"""Artifact API routes: create, list, get, update, delete.

GET    /api/artifacts                         — List artifacts for a conversation
GET    /api/artifacts/{id}                    — Get full artifact content
GET    /api/artifacts/{id}/render             — Get artifact ready for iframe render
PUT    /api/artifacts/{id}                    — Update artifact content
DELETE /api/artifacts/{id}                    — Delete artifact
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.services.artifacts import ArtifactStore

logger = structlog.get_logger()

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])

_store = ArtifactStore()


def get_artifact_store() -> ArtifactStore:
    return _store


class ArtifactUpdate(BaseModel):
    content: str = Field(..., min_length=1)
    title: str | None = None


@router.get("")
async def list_artifacts(conversation_id: str = "") -> list[dict]:
    """List artifacts, optionally filtered by conversation."""
    if conversation_id:
        artifacts = await _store.list_by_conversation(conversation_id)
    else:
        artifacts = list(_store._artifacts.values())
    return [a.to_summary() for a in artifacts]


@router.get("/{artifact_id}")
async def get_artifact(artifact_id: str) -> dict:
    """Get full artifact with content."""
    artifact = await _store.get(artifact_id)
    if not artifact:
        return {"error": "Artifact not found"}
    return artifact.to_dict()


@router.get("/{artifact_id}/render")
async def render_artifact(artifact_id: str) -> HTMLResponse:
    """Render artifact as HTML for iframe embedding.

    - html: served directly
    - svg: wrapped in HTML
    - mermaid: rendered with mermaid.js
    - code: syntax highlighted
    - markdown: rendered to HTML
    """
    artifact = await _store.get(artifact_id)
    if not artifact:
        return HTMLResponse("<p>Artifact not found</p>", status_code=404)

    if artifact.artifact_type == "html":
        return HTMLResponse(artifact.content)

    if artifact.artifact_type == "svg":
        html = f"""<!DOCTYPE html>
<html><head><style>body{{margin:0;display:flex;justify-content:center;align-items:center;min-height:100vh;background:#0d1117}}</style></head>
<body>{artifact.content}</body></html>"""
        return HTMLResponse(html)

    if artifact.artifact_type == "mermaid":
        html = f"""<!DOCTYPE html>
<html><head>
<script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
<style>body{{margin:20px;background:#0d1117;color:#e6edf3;font-family:sans-serif}}</style>
</head><body>
<pre class="mermaid">{artifact.content}</pre>
<script>mermaid.initialize({{startOnLoad:true,theme:'dark'}})</script>
</body></html>"""
        return HTMLResponse(html)

    if artifact.artifact_type == "code":
        escaped = artifact.content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        html = f"""<!DOCTYPE html>
<html><head>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
<style>body{{margin:0;background:#0d1117}}pre{{margin:16px;border-radius:8px}}</style>
</head><body>
<pre><code class="language-{artifact.language}">{escaped}</code></pre>
<script>hljs.highlightAll()</script>
</body></html>"""
        return HTMLResponse(html)

    # Default: show as preformatted text
    escaped = artifact.content.replace("<", "&lt;").replace(">", "&gt;")
    html = f"""<!DOCTYPE html>
<html><head><style>body{{margin:16px;background:#0d1117;color:#e6edf3;font-family:monospace;white-space:pre-wrap}}</style></head>
<body>{escaped}</body></html>"""
    return HTMLResponse(html)


@router.put("/{artifact_id}")
async def update_artifact(artifact_id: str, body: ArtifactUpdate) -> dict:
    """Update artifact content (creates new version)."""
    artifact = await _store.update_content(artifact_id, body.content, body.title)
    if not artifact:
        return {"error": "Artifact not found"}
    return artifact.to_dict()


@router.delete("/{artifact_id}", status_code=204)
async def delete_artifact(artifact_id: str) -> None:
    await _store.delete(artifact_id)
