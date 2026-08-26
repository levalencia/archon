"""Artifact system: agent generates viewable artifacts (HTML, code, SVG, etc).

Artifacts are rendered in a side panel like Claude's artifact viewer.
Each artifact is stored with the conversation and can be revisited.

Supported types:
- html: rendered in sandboxed iframe
- code: syntax-highlighted code block (any language)
- svg: rendered inline
- mermaid: rendered as diagram
- markdown: rendered as formatted text
- csv: rendered as table
- json: rendered with collapsible tree
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog

from app.security.persistence_redactor import PersistenceRedactor

logger = structlog.get_logger()


@dataclass
class Artifact:
    """A generated artifact with content and metadata."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str = ""
    message_id: str = ""
    user_id: str = ""
    title: str = "Untitled"
    artifact_type: str = "code"  # html, code, svg, mermaid, markdown, csv, json
    language: str = ""  # python, javascript, sql, etc. (for code type)
    content: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())
    version: int = 1

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "title": self.title,
            "type": self.artifact_type,
            "language": self.language,
            "content": self.content,
            "created_at": self.created_at,
            "version": self.version,
        }

    def to_summary(self) -> dict:
        """Summary without full content (for list views)."""
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "title": self.title,
            "type": self.artifact_type,
            "language": self.language,
            "content_length": len(self.content),
            "created_at": self.created_at,
            "version": self.version,
        }


class ArtifactStore:
    """In-memory artifact storage. PostgreSQL in production."""

    def __init__(self, redactor: PersistenceRedactor | None = None) -> None:
        self._artifacts: dict[str, Artifact] = {}
        self._by_conversation: dict[str, list[str]] = {}
        self._redactor = redactor or PersistenceRedactor()

    async def save(self, artifact: Artifact) -> Artifact:
        """Save or update an artifact."""
        artifact.title = self._redactor.redact_text(artifact.title).text
        artifact.content = self._redactor.redact_text(artifact.content).text
        self._artifacts[artifact.id] = artifact
        conv_list = self._by_conversation.setdefault(artifact.conversation_id, [])
        if artifact.id not in conv_list:
            conv_list.append(artifact.id)

        logger.info(
            "artifact_saved",
            artifact_id=artifact.id,
            type=artifact.artifact_type,
            size=len(artifact.content),
        )
        return artifact

    async def get(self, artifact_id: str) -> Artifact | None:
        return self._artifacts.get(artifact_id)

    async def list_by_conversation(self, conversation_id: str) -> list[Artifact]:
        ids = self._by_conversation.get(conversation_id, [])
        return [self._artifacts[aid] for aid in ids if aid in self._artifacts]

    async def list_by_user(self, user_id: str, conversation_id: str = "") -> list[Artifact]:
        artifacts = (
            await self.list_by_conversation(conversation_id)
            if conversation_id
            else list(self._artifacts.values())
        )
        return [artifact for artifact in artifacts if artifact.user_id == user_id]

    async def delete(self, artifact_id: str) -> bool:
        artifact = self._artifacts.pop(artifact_id, None)
        if artifact:
            conv_list = self._by_conversation.get(artifact.conversation_id, [])
            if artifact_id in conv_list:
                conv_list.remove(artifact_id)
            return True
        return False

    async def update_content(
        self, artifact_id: str, content: str, title: str | None = None
    ) -> Artifact | None:
        """Update artifact content (creates new version)."""
        artifact = self._artifacts.get(artifact_id)
        if not artifact:
            return None
        artifact.content = self._redactor.redact_text(content).text
        artifact.version += 1
        if title:
            artifact.title = self._redactor.redact_text(title).text
        return artifact


# Detection patterns for artifact types
ARTIFACT_MARKERS = {
    "html": [
        "<!DOCTYPE html>",
        "<html",
        "<!doctype html>",
    ],
    "svg": [
        "<svg",
        'xmlns="http://www.w3.org/2000/svg"',
    ],
    "mermaid": [
        "```mermaid",
        "graph TD",
        "graph LR",
        "graph TB",
        "sequenceDiagram",
        "classDiagram",
        "flowchart",
    ],
    "csv": [
        # Detected by structure, not markers
    ],
}


def detect_artifact_in_response(response: str) -> list[dict]:
    """Detect if the agent response contains renderable artifacts.

    Returns list of {type, content, title, language} for each artifact found.
    """
    artifacts = []

    # Check for HTML documents
    if any(marker in response for marker in ARTIFACT_MARKERS["html"]):
        # Extract HTML content
        start = response.find("<!DOCTYPE html>")
        if start == -1:
            start = response.find("<!doctype html>")
        if start == -1:
            start = response.find("<html")
        if start >= 0:
            end = response.find("</html>", start)
            if end > 0:
                html_content = response[start : end + 7]
                artifacts.append(
                    {
                        "type": "html",
                        "content": html_content,
                        "title": "Generated HTML",
                        "language": "html",
                    }
                )

    # Check for SVG
    if any(marker in response for marker in ARTIFACT_MARKERS["svg"]):
        start = response.find("<svg")
        if start >= 0:
            end = response.find("</svg>", start)
            if end > 0:
                svg_content = response[start : end + 6]
                artifacts.append(
                    {
                        "type": "svg",
                        "content": svg_content,
                        "title": "Generated SVG",
                        "language": "svg",
                    }
                )

    # Check for code blocks
    code_start = 0
    while True:
        idx = response.find("```", code_start)
        if idx == -1:
            break
        end_idx = response.find("```", idx + 3)
        if end_idx == -1:
            break

        block = response[idx + 3 : end_idx]
        # First line might be the language
        lines = block.split("\n", 1)
        lang = lines[0].strip() if lines[0].strip().isalpha() else ""
        code = lines[1] if len(lines) > 1 and lang else block

        # Skip mermaid (handled separately) and small blocks
        if lang != "mermaid" and len(code.strip()) > 50:
            artifacts.append(
                {
                    "type": "code",
                    "content": code.strip(),
                    "title": f"Code ({lang})" if lang else "Code",
                    "language": lang or "text",
                }
            )

        code_start = end_idx + 3

    # Check for Mermaid diagrams
    if any(marker in response for marker in ARTIFACT_MARKERS["mermaid"]):
        idx = response.find("```mermaid")
        if idx >= 0:
            end_idx = response.find("```", idx + 10)
            if end_idx > 0:
                mermaid_content = response[idx + 10 : end_idx].strip()
                artifacts.append(
                    {
                        "type": "mermaid",
                        "content": mermaid_content,
                        "title": "Diagram",
                        "language": "mermaid",
                    }
                )

    return artifacts
