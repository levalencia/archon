"""Skills system: load and search SKILL.md files from GitHub repos.

Skills are structured knowledge files that agents can load at runtime
to gain domain expertise. Similar to god-mode skill search.

See: https://github.com/levalencia/production-ai-agents/
Concept: Skills and MCP native (Architecture Principle 3.0)
"""

from __future__ import annotations

import re

import httpx
import structlog

logger = structlog.get_logger()


class Skill:
    """A loaded skill with metadata and content."""

    def __init__(
        self,
        name: str,
        description: str,
        content: str,
        source_url: str = "",
        tags: list[str] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.content = content
        self.source_url = source_url
        self.tags = tags or []

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "source_url": self.source_url,
            "tags": self.tags,
            "content_length": len(self.content),
        }


class SkillRegistry:
    """Registry of available skills. Supports local and GitHub sources."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        """Register a skill."""
        self._skills[skill.name] = skill
        logger.info("skill_registered", name=skill.name, tags=skill.tags)

    def get(self, name: str) -> Skill | None:
        """Get a skill by name."""
        return self._skills.get(name)

    def search(self, query: str, limit: int = 5) -> list[Skill]:
        """Search skills by keyword matching on name, description, and tags."""
        query_lower = query.lower()
        query_words = set(query_lower.split())

        scored: list[tuple[float, Skill]] = []
        for skill in self._skills.values():
            score = 0.0
            text = f"{skill.name} {skill.description} {' '.join(skill.tags)}".lower()

            for word in query_words:
                if word in skill.name.lower():
                    score += 3.0  # Name match weighted higher
                if word in skill.description.lower():
                    score += 1.0
                for tag in skill.tags:
                    if word in tag.lower():
                        score += 2.0

            if score > 0:
                scored.append((score, skill))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:limit]]

    def list_all(self) -> list[dict]:
        """List all registered skills."""
        return [s.to_dict() for s in self._skills.values()]

    def count(self) -> int:
        """Number of registered skills."""
        return len(self._skills)

    async def load_from_github(
        self,
        repo: str,
        path: str = "SKILL.md",
        branch: str = "main",
    ) -> Skill | None:
        """Load a skill from a GitHub repository.

        Args:
            repo: 'owner/repo' format
            path: path to SKILL.md in the repo
            branch: git branch
        """
        url = f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                content = response.text
        except Exception as e:
            logger.warning("skill_load_failed", repo=repo, path=path, error=str(e))
            return None

        # Parse frontmatter
        name = repo.split("/")[-1]
        description = ""
        tags: list[str] = []

        # Extract name/description from YAML frontmatter
        fm_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if fm_match:
            fm = fm_match.group(1)
            name_match = re.search(r"name:\s*(.+)", fm)
            if name_match:
                name = name_match.group(1).strip().strip("\"'")
            desc_match = re.search(r"description:\s*(.+)", fm)
            if desc_match:
                description = desc_match.group(1).strip().strip("\"'")
            tags_match = re.search(r"tags:\s*\[(.+?)\]", fm)
            if tags_match:
                tags = [t.strip().strip("\"'") for t in tags_match.group(1).split(",")]

        skill = Skill(
            name=name,
            description=description,
            content=content,
            source_url=url,
            tags=tags,
        )

        self.register(skill)
        logger.info("skill_loaded_from_github", repo=repo, name=name)
        return skill


def create_default_skills() -> SkillRegistry:
    """Create a registry with built-in Archon skills."""
    registry = SkillRegistry()

    registry.register(
        Skill(
            name="research-assistant",
            description="Help users research topics with web search and document analysis",
            content="Use web_search tool for current information. Use document query for uploaded docs.",
            tags=["research", "search", "rag"],
        )
    )

    registry.register(
        Skill(
            name="code-analysis",
            description="Analyze code snippets, explain algorithms, suggest improvements",
            content="Focus on readability, performance, and security. Cite best practices.",
            tags=["code", "analysis", "review"],
        )
    )

    registry.register(
        Skill(
            name="data-extraction",
            description="Extract structured data from unstructured text",
            content="Parse text for entities, dates, numbers, relationships. Return as JSON.",
            tags=["data", "extraction", "nlp"],
        )
    )

    return registry
