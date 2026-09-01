from __future__ import annotations

import pytest

from app.skills.installer import PinnedSkillSource, SkillSourceError, SkillSourcePolicy
from app.skills.parser import MAX_REFERENCES, SkillParseError, parse_skill_markdown


def skill(**overrides: str) -> bytes:
    values = {
        "name": "safe-skill",
        "description": "A safe skill",
        "version": "1.0.0",
        "extra": "tags: [safe]\nreferences: [references/guide.md]",
    }
    values.update(overrides)
    return (
        "---\n"
        f"name: {values['name']}\n"
        f"description: {values['description']}\n"
        f"version: {values['version']}\n"
        f"{values['extra']}\n"
        "---\nFollow these instructions.\n"
    ).encode()


def test_parser_uses_yaml_and_produces_stable_hashes() -> None:
    parsed = parse_skill_markdown(skill(description='"colon: is valid YAML"'))
    again = parse_skill_markdown(skill(description='"colon: is valid YAML"'))
    assert parsed.description == "colon: is valid YAML"
    assert parsed.references == ("references/guide.md",)
    assert parsed.content_hash == again.content_hash
    assert len(parsed.manifest_hash) == 64


@pytest.mark.parametrize(
    "payload",
    [
        skill(extra="name: duplicate"),
        skill(extra="references: [../secret]"),
        skill(extra="references: [/etc/passwd]"),
        skill(extra="references: [C:/secret]"),
        skill(extra="tags: &tags [safe]\nreferences: *tags"),
        b"---\nname: [unterminated\n---\nbody\n",
        b"name: no-frontmatter\n",
    ],
)
def test_parser_rejects_malformed_or_unsafe_manifests(payload: bytes) -> None:
    with pytest.raises(SkillParseError):
        parse_skill_markdown(payload)


def test_parser_enforces_byte_and_reference_caps() -> None:
    with pytest.raises(SkillParseError, match="exceeds"):
        parse_skill_markdown(skill() + b"x" * 100, max_bytes=len(skill()))
    refs = ", ".join(f"refs/{index}.md" for index in range(MAX_REFERENCES + 1))
    with pytest.raises(SkillParseError, match="references"):
        parse_skill_markdown(skill(extra=f"references: [{refs}]"))


def test_source_policy_requires_allowlist_pin_and_safe_path() -> None:
    policy = SkillSourcePolicy(allowed_repositories=frozenset({"nous/approved"}))
    pin = "a" * 40
    assert policy.resolve(PinnedSkillSource("nous/approved", pin)) == (
        f"https://raw.githubusercontent.com/nous/approved/{pin}/SKILL.md"
    )
    for source in (
        PinnedSkillSource("attacker/repo", pin),
        PinnedSkillSource("nous/approved", "main"),
        PinnedSkillSource("nous/approved", pin, "../SKILL.md"),
    ):
        with pytest.raises(SkillSourceError):
            policy.resolve(source)
