#!/usr/bin/env python3
"""Opt-in real embedding smoke; never prints credentials."""

from __future__ import annotations

import asyncio
import os

from app.services.chunker import EmbeddingService


async def main() -> None:
    provider = os.getenv("ARCHON_EMBEDDING_PROVIDER", "")
    key = os.getenv("ARCHON_EMBEDDING_API_KEY", "")
    if not provider or provider == "mock" or not key:
        raise SystemExit("Set a non-mock ARCHON_EMBEDDING_PROVIDER and ARCHON_EMBEDDING_API_KEY")
    dimensions = int(os.getenv("ARCHON_EMBEDDING_DIMENSIONS", "256"))
    service = EmbeddingService(
        provider=provider,
        model=os.getenv("ARCHON_EMBEDDING_MODEL", "text-embedding-3-small"),
        api_key=key,
        dimensions=dimensions,
        base_url=os.getenv("ARCHON_EMBEDDING_BASE_URL", "https://api.openai.com/v1"),
    )
    service.validate_configuration()
    vector = await service.embed("Archon embedding capability smoke")
    capability = service.capability
    print(f"provider={capability.provider} model={capability.model} dimensions={len(vector)}")


if __name__ == "__main__":
    asyncio.run(main())
