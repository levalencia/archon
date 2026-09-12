#!/usr/bin/env python3
"""Synchronize canonical repository and video knowledge into the local tutor index."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import subprocess
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.learning_media.catalog import LearningMediaCatalog
from app.learning_tutor.indexer import collect_learning_corpus
from app.learning_tutor.repository import LearningKnowledgeRepository
from app.security.persistence_redactor import PersistenceRedactor
from app.services.chunker import EmbeddingService
from app.services.db_store import DatabaseStore


def _revision(root: Path, allow_dirty: bool) -> str:
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if not status:
        return sha
    if not allow_dirty:
        raise SystemExit("Refusing to index a dirty repository without --allow-dirty")
    digest = hashlib.sha256(
        subprocess.run(
            ["git", "diff", "--binary", "HEAD"], cwd=root, check=True, capture_output=True
        ).stdout
    )
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout.split(b"\0")
    for encoded_path in sorted(item for item in untracked if item):
        path = root / encoded_path.decode("utf-8")
        if path.is_file() and not path.is_symlink():
            digest.update(encoded_path)
            digest.update(path.read_bytes())
    return f"working-tree:{digest.hexdigest()[:16]}"


async def _run(args: argparse.Namespace) -> None:
    root = args.repository_root.resolve()
    revision = args.revision or _revision(root, args.allow_dirty)
    media_catalog = LearningMediaCatalog(args.media_root) if args.media_root else None
    sources = collect_learning_corpus(
        repository_root=root,
        studio_path=root / "frontend/static/learning/cogentrex-studio.json",
        revision=revision,
        media_catalog=media_catalog,
        video_artifact_ids=set(args.video) if args.video else None,
        include_review_ready=args.include_review_ready,
    )
    counts: dict[str, int] = {}
    for source in sources:
        counts[source.kind] = counts.get(source.kind, 0) + 1
    print(f"revision={revision} sources={len(sources)} kinds={counts}")
    if args.dry_run:
        return
    settings = Settings(database_url=args.database_url) if args.database_url else Settings()
    embedding_provider = "mock" if args.mock_embeddings else settings.embedding_provider
    embeddings = EmbeddingService(
        provider=embedding_provider,
        model=settings.embedding_model,
        api_key="" if args.mock_embeddings else settings.embedding_api_key or settings.llm_api_key,
        dimensions=settings.embedding_dimensions,
        base_url=settings.embedding_base_url,
        allowed_hosts=settings.embedding_allowed_hosts,
        allow_private_endpoint=settings.embedding_allow_private_endpoint,
        api_version=settings.embedding_api_version,
    )
    embeddings.validate_configuration()
    if embeddings.capability.mock and not args.allow_mock:
        raise SystemExit("Refusing semantic index with mock embeddings without --allow-mock")
    store = DatabaseStore(settings.database_url)
    await store.initialize()
    try:
        repository = LearningKnowledgeRepository(
            store.session_factory,
            embeddings,
            PersistenceRedactor(),
            candidate_limit=settings.vector_search_candidate_limit,
        )
        result = await repository.sync(sources)
        print(f"sync={result} total={await repository.count_sources()}")
    finally:
        await embeddings.close()
        await store.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).parents[1])
    parser.add_argument("--media-root", type=Path)
    parser.add_argument("--database-url")
    parser.add_argument("--revision")
    parser.add_argument("--video", action="append", default=[])
    parser.add_argument("--include-review-ready", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--allow-mock", action="store_true")
    parser.add_argument(
        "--mock-embeddings",
        action="store_true",
        help="Build a deterministic lexical-development index without provider calls.",
    )
    parser.add_argument("--dry-run", action="store_true")
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()
