"""Resolve untrusted browser context against canonical learning manifests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.learning_media.catalog import LearningMediaCatalog

LearningView = Literal[
    "roadmap", "stories", "architecture", "evidence", "present", "listen", "study"
]


class LearningContextRequest(BaseModel):
    """Identifiers supplied by the UI; source paths are deliberately not accepted."""

    model_config = ConfigDict(extra="forbid")

    view: LearningView
    concept_id: str | None = Field(default=None, max_length=255)
    module_id: str | None = Field(default=None, max_length=255)
    story_id: str | None = Field(default=None, max_length=255)
    step_index: int | None = Field(default=None, ge=0, le=100)
    artifact_id: str | None = Field(default=None, max_length=255)
    playback_seconds: float | None = Field(default=None, ge=0)
    selected_node_id: str | None = Field(default=None, max_length=255)
    selected_edge_id: str | None = Field(default=None, max_length=255)


@dataclass(frozen=True, slots=True)
class LearningTranscriptSegment:
    chapter: str
    text: str
    start_seconds: float
    end_seconds: float
    sources: tuple[dict[str, Any] | str, ...]


@dataclass(frozen=True, slots=True)
class LearningContext:
    context_key: str
    view: LearningView
    title: str
    concept_ids: tuple[str, ...]
    module_id: str | None
    story_id: str | None
    step_index: int | None
    artifact_id: str | None
    playback_seconds: float | None
    selected_node_id: str | None
    selected_edge_id: str | None
    source_commit: str | None
    source_references: tuple[dict[str, Any] | str, ...]
    segment: LearningTranscriptSegment | None = None

    def public(self) -> dict[str, Any]:
        return {
            "context_key": self.context_key,
            "view": self.view,
            "title": self.title,
            "concept_ids": list(self.concept_ids),
            "module_id": self.module_id,
            "story_id": self.story_id,
            "step_index": self.step_index,
            "artifact_id": self.artifact_id,
            "playback_seconds": self.playback_seconds,
            "selected_node_id": self.selected_node_id,
            "selected_edge_id": self.selected_edge_id,
            "source_commit": self.source_commit,
            "source_references": list(self.source_references),
            "segment": (
                {
                    "chapter": self.segment.chapter,
                    "text": self.segment.text,
                    "start_seconds": self.segment.start_seconds,
                    "end_seconds": self.segment.end_seconds,
                    "sources": list(self.segment.sources),
                }
                if self.segment is not None
                else None
            ),
        }


class LearningContextResolver:
    """Resolve page selections from trusted server-owned manifests."""

    def __init__(
        self,
        *,
        studio_path: str | Path,
        media_catalog: LearningMediaCatalog | None = None,
    ) -> None:
        self._studio_path = Path(studio_path).resolve()
        try:
            payload = json.loads(self._studio_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Visual Learning manifest is missing or invalid") from exc
        if payload.get("schema") != "cogentrex.visual-learning-studio":
            raise ValueError("Visual Learning manifest has an unsupported schema")
        self._studio: dict[str, Any] = payload
        self._concepts = {
            str(item["id"]): item for item in payload.get("concepts", []) if isinstance(item, dict)
        }
        self._modules = {
            str(item["id"]): item for item in payload.get("modules", []) if isinstance(item, dict)
        }
        self._stories = {
            str(item["id"]): item for item in payload.get("stories", []) if isinstance(item, dict)
        }
        architecture = payload.get("architecture", {})
        layers = architecture.get("layers", []) if isinstance(architecture, dict) else []
        self._architecture_nodes = {
            str(component["id"]): component
            for layer in layers
            if isinstance(layer, dict)
            for component in layer.get("components", [])
            if isinstance(component, dict) and component.get("id")
        }
        relations = architecture.get("relations", []) if isinstance(architecture, dict) else []
        self._architecture_edges = {
            str(
                relation.get("id")
                or f"{relation.get('source')}:{relation.get('type')}:{relation.get('target')}"
            ): relation
            for relation in relations
            if isinstance(relation, dict)
        }
        self._media_catalog = media_catalog

    def resolve(self, request: LearningContextRequest) -> LearningContext:
        if request.artifact_id is not None:
            return self._resolve_artifact(request)
        if request.story_id is not None:
            return self._resolve_story(request)
        if request.selected_node_id is not None or request.selected_edge_id is not None:
            return self._resolve_architecture(request)
        if request.concept_id is not None:
            concept = self._concepts.get(request.concept_id)
            if concept is None:
                raise ValueError("Unknown learning concept")
            return LearningContext(
                context_key=f"concept:{request.concept_id}",
                view=request.view,
                title=str(concept.get("title") or request.concept_id),
                concept_ids=(request.concept_id,),
                module_id=request.module_id,
                story_id=request.story_id,
                step_index=request.step_index,
                artifact_id=None,
                playback_seconds=None,
                selected_node_id=request.selected_node_id,
                selected_edge_id=request.selected_edge_id,
                source_commit=None,
                source_references=tuple(concept.get("sources", [])),
            )
        if request.module_id is not None:
            module = self._modules.get(request.module_id)
            if module is None:
                raise ValueError("Unknown learning module")
            return LearningContext(
                context_key=f"module:{request.module_id}",
                view=request.view,
                title=str(module.get("title") or request.module_id),
                concept_ids=tuple(str(item) for item in module.get("concept_ids", [])),
                module_id=request.module_id,
                story_id=None,
                step_index=None,
                artifact_id=None,
                playback_seconds=None,
                selected_node_id=request.selected_node_id,
                selected_edge_id=request.selected_edge_id,
                source_commit=None,
                source_references=(),
            )
        return LearningContext(
            context_key=f"view:{request.view}",
            view=request.view,
            title=f"Visual Learning: {request.view.title()}",
            concept_ids=(),
            module_id=None,
            story_id=None,
            step_index=None,
            artifact_id=None,
            playback_seconds=None,
            selected_node_id=request.selected_node_id,
            selected_edge_id=request.selected_edge_id,
            source_commit=None,
            source_references=(),
        )

    def _resolve_architecture(self, request: LearningContextRequest) -> LearningContext:
        concept_ids: list[str] = []
        title = "Architecture"
        context_key = "architecture"
        if request.selected_node_id is not None:
            node = self._architecture_nodes.get(request.selected_node_id)
            if node is None:
                raise ValueError("Unknown architecture component")
            concept_ids.extend(str(item) for item in node.get("concept_ids", []))
            title = str(node.get("title") or request.selected_node_id)
            context_key = f"architecture:node:{request.selected_node_id}"
        if request.selected_edge_id is not None:
            edge = self._architecture_edges.get(request.selected_edge_id)
            if edge is None:
                raise ValueError("Unknown architecture relation")
            for endpoint in (edge.get("source"), edge.get("target")):
                node = self._architecture_nodes.get(str(endpoint))
                if node is not None:
                    concept_ids.extend(str(item) for item in node.get("concept_ids", []))
            title = str(edge.get("label") or request.selected_edge_id)
            context_key = f"architecture:edge:{request.selected_edge_id}"
        if request.concept_id is not None:
            if request.concept_id not in self._concepts:
                raise ValueError("Unknown learning concept")
            concept_ids.append(request.concept_id)
        return LearningContext(
            context_key=context_key,
            view=request.view,
            title=title,
            concept_ids=tuple(dict.fromkeys(concept_ids)),
            module_id=None,
            story_id=None,
            step_index=None,
            artifact_id=None,
            playback_seconds=None,
            selected_node_id=request.selected_node_id,
            selected_edge_id=request.selected_edge_id,
            source_commit=None,
            source_references=(),
        )

    def _resolve_story(self, request: LearningContextRequest) -> LearningContext:
        story = self._stories.get(str(request.story_id))
        if story is None:
            raise ValueError("Unknown learning story")
        steps = story.get("steps", [])
        concept_ids: tuple[str, ...] = ()
        if request.step_index is not None:
            if not isinstance(steps, list) or request.step_index >= len(steps):
                raise ValueError("Unknown learning story step")
            step = steps[request.step_index]
            if isinstance(step, dict):
                concept_ids = tuple(str(item) for item in step.get("concept_ids", []))
        return LearningContext(
            context_key=(
                f"story:{request.story_id}:step:{request.step_index}"
                if request.step_index is not None
                else f"story:{request.story_id}"
            ),
            view=request.view,
            title=str(story.get("title") or request.story_id),
            concept_ids=concept_ids,
            module_id=None,
            story_id=request.story_id,
            step_index=request.step_index,
            artifact_id=None,
            playback_seconds=None,
            selected_node_id=request.selected_node_id,
            selected_edge_id=request.selected_edge_id,
            source_commit=None,
            source_references=(),
        )

    def _resolve_artifact(self, request: LearningContextRequest) -> LearningContext:
        if self._media_catalog is None:
            raise ValueError("Learning media is unavailable")
        try:
            artifact = self._media_catalog.artifact(str(request.artifact_id))
        except KeyError as exc:
            raise ValueError("Unknown learning artifact") from exc
        metadata = artifact.metadata
        duration = metadata.get("duration_seconds")
        if request.playback_seconds is not None and (
            not isinstance(duration, (int, float)) or request.playback_seconds > float(duration)
        ):
            raise ValueError("Invalid video playback position")
        segment = self._segment_at(artifact.content_path, request.playback_seconds)
        sources: list[dict[str, Any] | str] = []
        if segment is not None:
            sources.extend(segment.sources)
        return LearningContext(
            context_key=f"artifact:{request.artifact_id}",
            view=request.view,
            title=str(metadata.get("title") or request.artifact_id),
            concept_ids=tuple(str(item) for item in metadata.get("concept_ids", [])),
            module_id=None,
            story_id=None,
            step_index=None,
            artifact_id=request.artifact_id,
            playback_seconds=request.playback_seconds,
            selected_node_id=request.selected_node_id,
            selected_edge_id=request.selected_edge_id,
            source_commit=str(metadata.get("source_commit") or "") or None,
            source_references=tuple(sources),
            segment=segment,
        )

    @staticmethod
    def _segment_at(
        content_path: Path | None, playback_seconds: float | None
    ) -> LearningTranscriptSegment | None:
        if (
            content_path is None
            or playback_seconds is None
            or content_path.suffix.lower() != ".json"
        ):
            return None
        try:
            payload = json.loads(content_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        segments = payload.get("segments", [])
        if not isinstance(segments, list):
            return None
        for raw in segments:
            if not isinstance(raw, dict):
                continue
            start = raw.get("start_seconds")
            end = raw.get("end_seconds")
            if (
                isinstance(start, (int, float))
                and isinstance(end, (int, float))
                and float(start) <= playback_seconds <= float(end)
            ):
                return LearningTranscriptSegment(
                    chapter=str(raw.get("chapter") or "Transcript"),
                    text=str(raw.get("text") or ""),
                    start_seconds=float(start),
                    end_seconds=float(end),
                    sources=tuple(raw.get("sources", [])),
                )
        return None
