"""Pinned, allowlisted skill source installation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Protocol
from urllib.parse import quote, urlsplit

import httpx

from app.skills.parser import MAX_SKILL_BYTES, ParsedSkill, SkillParseError, parse_skill_markdown
from app.skills.persistence import InstalledSkill, SkillRepository

_PIN = re.compile(r"^[0-9a-f]{40}$")


class SkillSourceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PinnedSkillSource:
    repository: str
    revision: str
    path: str = "SKILL.md"


class SkillFetcher(Protocol):
    async def fetch(self, url: str, *, max_bytes: int) -> bytes: ...


class HttpSkillFetcher:
    async def fetch(self, url: str, *, max_bytes: int) -> bytes:
        chunks: list[bytes] = []
        size = 0
        async with (
            httpx.AsyncClient(follow_redirects=False, timeout=15.0) as client,
            client.stream("GET", url) as response,
        ):
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    raise SkillSourceError("remote SKILL.md exceeds byte limit")
                chunks.append(chunk)
        return b"".join(chunks)


class SkillSourcePolicy:
    """Construct immutable raw URLs; callers cannot provide arbitrary hosts."""

    def __init__(self, *, allowed_repositories: frozenset[str]) -> None:
        self._allowed = allowed_repositories

    def resolve(self, source: PinnedSkillSource) -> str:
        if source.repository not in self._allowed:
            raise SkillSourceError("repository is not allowlisted")
        parts = source.repository.split("/")
        if len(parts) != 2 or any(not part or part in {".", ".."} for part in parts):
            raise SkillSourceError("repository must be owner/name")
        if not _PIN.fullmatch(source.revision):
            raise SkillSourceError("source revision must be a lowercase 40-character commit SHA")
        if "\\" in source.path:
            raise SkillSourceError("source path must use POSIX separators")
        path = PurePosixPath(source.path)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise SkillSourceError("source path must stay inside the repository")
        encoded_path = "/".join(quote(part, safe="-._~") for part in path.parts)
        url = (
            f"https://raw.githubusercontent.com/{quote(parts[0], safe='-._~')}/"
            f"{quote(parts[1], safe='-._~')}/{source.revision}/{encoded_path}"
        )
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != "raw.githubusercontent.com":
            raise SkillSourceError("resolved source host is not allowed")
        return url


class SkillInstallationService:
    def __init__(
        self, repository: SkillRepository, policy: SkillSourcePolicy, fetcher: SkillFetcher
    ) -> None:
        self._repository = repository
        self._policy = policy
        self._fetcher = fetcher

    async def install(
        self,
        *,
        owner_id: str,
        source: PinnedSkillSource,
        trust_state: str = "untrusted",
        review_state: str = "pending",
    ) -> InstalledSkill:
        url = self._policy.resolve(source)
        data = await self._fetcher.fetch(url, max_bytes=MAX_SKILL_BYTES)
        try:
            parsed: ParsedSkill = parse_skill_markdown(data)
        except SkillParseError:
            raise
        return await self._repository.install(
            owner_id=owner_id,
            parsed=parsed,
            source_url=url,
            source_revision=source.revision,
            trust_state=trust_state,
            review_state=review_state,
        )
