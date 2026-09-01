"""Validated Archon-owned skills distributed with the runtime."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files

from app.skills.parser import ParsedSkill, SkillParseError, parse_skill_markdown

ARCHON_OWNER_ID = "archon"


@dataclass(frozen=True, slots=True)
class BundledSkill:
    parsed: ParsedSkill
    references: dict[str, str]


def bundled_skills() -> tuple[BundledSkill, ...]:
    root = files(__package__)
    result = []
    directories = (
        item for item in root.iterdir() if item.is_dir() and item.joinpath("SKILL.md").is_file()
    )
    for directory in sorted(directories, key=lambda x: x.name):
        parsed = parse_skill_markdown(directory.joinpath("SKILL.md").read_bytes())
        if (
            not parsed.triggers
            or not parsed.negative_triggers
            or not parsed.required_capability_ids
        ):
            raise SkillParseError(f"bundled skill {parsed.name} lacks governed discovery metadata")
        references = {
            path: directory.joinpath(path).read_text(encoding="utf-8") for path in parsed.references
        }
        result.append(BundledSkill(parsed, references))
    if len(result) != 10:
        raise SkillParseError("the runtime must contain exactly ten bundled skills")
    return tuple(result)
