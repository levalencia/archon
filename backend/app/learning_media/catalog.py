"""Validated, read-only learning-media catalog."""

from __future__ import annotations

import hashlib
import hmac
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from app.learning_media.paths import media_type_for, resolve_published_file

_ALLOWED_TYPES = {
    "deck",
    "diagram",
    "infographic",
    "audio",
    "podcast",
    "mind-map",
    "flashcards",
    "quiz",
    "study-guide",
    "video",
}
_ALLOWED_STATUSES = {"review-ready", "published", "stale"}


@dataclass(frozen=True, slots=True)
class PublishedArtifact:
    """Validated artifact metadata plus its private resolved path."""

    metadata: dict[str, Any]
    path: Path
    content_path: Path | None = None


class LearningMediaCatalog:
    """Load and validate the atomically published learning-media catalog."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self._payload = self._load()
        self._artifacts = self._index(self._payload)

    def _load(self) -> dict[str, Any]:
        catalog_path = self.root / "catalog.json"
        try:
            payload = json.loads(catalog_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("learning-media catalog is missing or invalid") from error
        if payload.get("schema") != "archon.learning-library" or payload.get("version") != 1:
            raise ValueError("unsupported learning-media catalog schema")
        packs = payload.get("packs")
        if not isinstance(packs, list):
            raise ValueError("learning-media catalog packs must be a list")
        return cast(dict[str, Any], payload)

    def _index(self, payload: dict[str, Any]) -> dict[str, PublishedArtifact]:
        indexed: dict[str, PublishedArtifact] = {}
        for pack in payload["packs"]:
            if not isinstance(pack, dict) or not all(
                pack.get(key) for key in ("id", "title", "purpose")
            ):
                raise ValueError("invalid learning-media pack")
            artifacts = pack.get("artifacts")
            if not isinstance(artifacts, list):
                raise ValueError("learning-media artifacts must be a list")
            for raw in artifacts:
                if not isinstance(raw, dict):
                    raise ValueError("invalid learning-media artifact")
                artifact_id = raw.get("id")
                if not artifact_id or artifact_id in indexed:
                    raise ValueError("learning-media artifact IDs must be present and unique")
                if raw.get("status") not in _ALLOWED_STATUSES:
                    raise ValueError(f"artifact {artifact_id} is not publishable")
                if raw.get("type") not in _ALLOWED_TYPES or raw.get("language") != "en":
                    raise ValueError(f"artifact {artifact_id} has an unsupported type or language")
                if not isinstance(raw.get("limitations"), list) or not raw["limitations"]:
                    raise ValueError(f"artifact {artifact_id} must declare limitations")
                path = resolve_published_file(self.root, str(raw.get("file", "")))
                declared_media_type = str(raw.get("media_type", "")).split(";", 1)[0]
                actual_media_type = media_type_for(path).split(";", 1)[0]
                if declared_media_type != actual_media_type:
                    raise ValueError(f"artifact {artifact_id} media type mismatch")
                expected = str(raw.get("sha256", ""))
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
                if len(expected) != 64 or not hmac.compare_digest(expected, actual):
                    raise ValueError(f"artifact {artifact_id} checksum mismatch")
                content_path = None
                if raw.get("content_file"):
                    content_path = resolve_published_file(self.root, str(raw["content_file"]))
                    expected_content = str(raw.get("content_sha256", ""))
                    actual_content = hashlib.sha256(content_path.read_bytes()).hexdigest()
                    if len(expected_content) != 64 or not hmac.compare_digest(
                        expected_content, actual_content
                    ):
                        raise ValueError(f"artifact {artifact_id} content checksum mismatch")
                indexed[artifact_id] = PublishedArtifact(deepcopy(raw), path, content_path)
        return indexed

    def artifact(self, artifact_id: str) -> PublishedArtifact:
        try:
            return self._artifacts[artifact_id]
        except KeyError as error:
            raise KeyError("learning-media artifact not found") from error

    def public_catalog(self) -> dict[str, Any]:
        payload = deepcopy(self._payload)
        for pack in payload["packs"]:
            for artifact in pack["artifacts"]:
                artifact.pop("file", None)
                artifact.pop("content_file", None)
        return payload
