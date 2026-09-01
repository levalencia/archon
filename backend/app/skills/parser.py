"""Strict, bounded parser for portable ``SKILL.md`` packages."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import yaml

MAX_SKILL_BYTES = 256 * 1024
MAX_REFERENCES = 32
MAX_REFERENCE_BYTES = 1024
MAX_TAGS = 32
_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_ALLOWED_KEYS = {
    "name",
    "description",
    "version",
    "tags",
    "references",
    "triggers",
    "negative_triggers",
    "required_capability_ids",
    "context_cost",
}


class SkillParseError(ValueError):
    """The package manifest is malformed or exceeds a safety boundary."""


class _UniqueKeyLoader(yaml.SafeLoader):
    def compose_node(self, parent: yaml.Node | None, index: int) -> yaml.Node:
        if self.check_event(yaml.AliasEvent):
            raise SkillParseError("YAML aliases are not allowed")
        node = super().compose_node(parent, index)
        if node is None:  # pragma: no cover - defensive against malformed loader state
            raise SkillParseError("invalid YAML node")
        return node


def _construct_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> Any:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise SkillParseError(f"duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


@dataclass(frozen=True, slots=True)
class ParsedSkill:
    name: str
    description: str
    version: str
    tags: tuple[str, ...]
    references: tuple[str, ...]
    triggers: tuple[str, ...]
    negative_triggers: tuple[str, ...]
    required_capability_ids: tuple[str, ...]
    context_cost: int
    instructions: str
    raw_content: str
    content_hash: str
    manifest_hash: str


def _safe_reference(value: object) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > MAX_REFERENCE_BYTES:
        raise SkillParseError("reference must be a non-empty bounded string")
    if "\\" in value or "\x00" in value:
        raise SkillParseError("reference path must use safe POSIX syntax")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise SkillParseError("reference path must stay inside the package")
    if value.startswith("~") or ":" in path.parts[0]:
        raise SkillParseError("reference path must stay inside the package")
    return value


def parse_skill_markdown(data: bytes, *, max_bytes: int = MAX_SKILL_BYTES) -> ParsedSkill:
    """Parse a UTF-8 SKILL.md with exact YAML frontmatter and bounded references."""
    if len(data) > max_bytes:
        raise SkillParseError(f"SKILL.md exceeds {max_bytes} bytes")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SkillParseError("SKILL.md must be UTF-8") from exc
    if "\r" in text:
        raise SkillParseError("SKILL.md must use canonical LF line endings")
    if not text.startswith("---\n"):
        raise SkillParseError("SKILL.md must start with YAML frontmatter")
    marker = text.find("\n---\n", 4)
    if marker < 0:
        raise SkillParseError("SKILL.md frontmatter is not terminated")
    raw_manifest = text[4:marker]
    instructions = text[marker + 5 :]
    if not instructions.strip():
        raise SkillParseError("SKILL.md instructions must not be empty")
    try:
        manifest = yaml.load(raw_manifest, Loader=_UniqueKeyLoader)
    except (yaml.YAMLError, SkillParseError) as exc:
        raise SkillParseError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(manifest, dict) or not all(isinstance(k, str) for k in manifest):
        raise SkillParseError("frontmatter must be a string-keyed mapping")
    unknown = set(manifest) - _ALLOWED_KEYS
    if unknown:
        raise SkillParseError(f"unknown frontmatter keys: {sorted(unknown)}")
    name = manifest.get("name")
    description = manifest.get("description")
    version = manifest.get("version")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise SkillParseError("name must be a lowercase package identifier")
    if not isinstance(description, str) or not description.strip() or len(description) > 2000:
        raise SkillParseError("description must be a non-empty string of at most 2000 characters")
    if not isinstance(version, str) or not version.strip() or len(version) > 128:
        raise SkillParseError("version must be a non-empty string of at most 128 characters")
    raw_tags = manifest.get("tags", [])
    if not isinstance(raw_tags, list) or len(raw_tags) > MAX_TAGS:
        raise SkillParseError(f"tags must be a list with at most {MAX_TAGS} items")
    if any(not isinstance(tag, str) or not tag or len(tag) > 64 for tag in raw_tags):
        raise SkillParseError("tags must be non-empty strings of at most 64 characters")
    raw_references = manifest.get("references", [])
    if not isinstance(raw_references, list) or len(raw_references) > MAX_REFERENCES:
        raise SkillParseError(f"references must be a list with at most {MAX_REFERENCES} items")
    references = tuple(_safe_reference(item) for item in raw_references)

    def terms(key: str, maximum: int = 32) -> tuple[str, ...]:
        raw = manifest.get(key, [])
        if not isinstance(raw, list) or len(raw) > maximum:
            raise SkillParseError(f"{key} must be a list with at most {maximum} items")
        if any(not isinstance(item, str) or not item.strip() or len(item) > 128 for item in raw):
            raise SkillParseError(f"{key} must contain bounded non-empty strings")
        if len(set(raw)) != len(raw):
            raise SkillParseError(f"{key} values must be unique")
        return tuple(raw)

    triggers = terms("triggers")
    negative_triggers = terms("negative_triggers")
    required_capability_ids = terms("required_capability_ids")
    if any(not _NAME.fullmatch(item) for item in required_capability_ids):
        raise SkillParseError("required_capability_ids must contain capability identifiers")
    context_cost = manifest.get("context_cost", len(instructions.encode("utf-8")))
    if type(context_cost) is not int or not 0 <= context_cost <= MAX_SKILL_BYTES:
        raise SkillParseError("context_cost must be a bounded non-negative integer")
    canonical_manifest = yaml.safe_dump(manifest, sort_keys=True, allow_unicode=True).encode(
        "utf-8"
    )
    return ParsedSkill(
        name=name,
        description=description.strip(),
        version=version.strip(),
        tags=tuple(raw_tags),
        references=references,
        triggers=triggers,
        negative_triggers=negative_triggers,
        required_capability_ids=required_capability_ids,
        context_cost=context_cost,
        instructions=instructions,
        raw_content=text,
        content_hash=hashlib.sha256(data).hexdigest(),
        manifest_hash=hashlib.sha256(canonical_manifest).hexdigest(),
    )
