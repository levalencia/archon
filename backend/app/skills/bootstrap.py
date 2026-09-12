"""Idempotent bootstrap of immutable Cogentrex-owned bundled skill revisions."""

from __future__ import annotations

from app.skills.bundled import COGENTREX_OWNER_ID, bundled_skills
from app.skills.persistence import InstalledSkill, SkillRepository


class BundledSkillBootstrap:
    def __init__(self, repository: SkillRepository) -> None:
        self._repository = repository

    async def install(self) -> tuple[InstalledSkill, ...]:
        installed = []
        for skill in bundled_skills():
            installed.append(
                await self._repository.install(
                    owner_id=COGENTREX_OWNER_ID,
                    parsed=skill.parsed,
                    source_url=f"bundled://cogentrex/{skill.parsed.name}/SKILL.md",
                    source_revision=skill.parsed.content_hash,
                    trust_state="verified",
                    review_state="approved",
                    reference_contents=skill.references,
                )
            )
        return tuple(installed)
