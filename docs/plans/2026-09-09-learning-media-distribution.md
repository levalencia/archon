# Learning Media Distribution Plan

**Date:** 2026-09-09
**Status:** Implemented and release asset verified; repository integration pending
**Branch:** `feat/learning-media-distribution`
**Source commit:** `07b527103e2863e09a71802463f5af91c37eb69e`

## Problem

Cogentrex's rich Visual Learning media (audio, video, SVGs, HTML decks, study
materials) lives outside Git in an external sibling library. Anyone cloning
Cogentrex cannot access these files without manual setup. We need a secure,
reproducible distribution path via GitHub Release assets.

## Design

### Packaging (`package` subcommand)

1. Read the external library at `--library` path.
2. Validate `catalog.json`: schema=`cogentrex.learning-library`, version=1,
   full 40-hex source_commit, non-empty packs with non-empty artifacts,
   artifact `file` paths must be relative `published/**` paths contained
   under library root, not symlinks, regular files only. SHA-256 checksums
   validated by streaming (not `read_bytes`). `content_file`/`content_sha256`
   also validated when present.
3. Reject symlinks, FIFOs, device nodes, and other non-regular files.
4. Create a **deterministic** tar.gz archive containing only:
   - `.cogentrex-learning-library` (ownership marker)
   - `catalog.json`
   - `published/**` (all published artifacts)
5. Streaming: files streamed into tar→gzip→file (no full in-memory BytesIO).
   Cumulative input size capped. Output parent directories created automatically.
6. Determinism: stable sorted entry order, normalized uid/gid/uname/gname
   (all `0`/`root`), zero mtime on all entries, zero gzip header mtime.
7. Emit a release manifest JSON with: `schema_version` (1), `release_tag`,
   `source_commit`, `asset_name`, `download_url` (HTTPS), `byte_size`,
   `archive_sha256`.

### Installation (`install` subcommand)

1. **Manifest always required**: both `--archive` (offline) and online modes
   require `--manifest` pointing to a trusted manifest. Local archives never
   self-compute trust data.
2. **Manifest validation first**: before any network or filesystem work, validate
   `schema_version=1`, positive integer `byte_size`, 64 lowercase hex
   `archive_sha256`, full 40-hex `source_commit`, correct tag/asset naming
   (`learning-media-<short12>` / `cogentrex-learning-media-<short12>.tar.gz`),
   and `download_url` exactly matching
   `https://github.com/levalencia/cogentrex/releases/download/<tag>/<asset>`.
   Null or missing fields fail immediately.
3. **Target outside repo**: install target must be outside the repository root.
4. **Size bounds before hashing**: reject archives outside `[MIN, MAX]` before
   streaming SHA-256.
5. **Streaming hash**: SHA-256 computed by streaming 64 KiB chunks, never `read_bytes`.
6. **HTTPS download**: stream with Content-Length check, hard running byte cap,
   reject redirects/final URLs outside the allowlisted GitHub release hosts.
7. **Tar security** (streaming, no `getmembers`):
   - Reject absolute paths, `..` traversal, symlinks, hard links, devices, FIFOs.
   - Only regular files and directories allowed.
   - Reject unexpected top-level entries (only marker, catalog, published).
   - Reject duplicate member names.
   - Per-member uncompressed size cap (500 MiB).
   - Cumulative uncompressed size cap (4 GiB).
   - Member count cap (50,000).
8. Post-extraction: validate marker, catalog.json, and call the same
   `validate_catalog` as packaging. `PackageError` translated to `InstallError`.
9. **Atomic replacement**: unique sibling backup (`<name>.old-<uuid8>`), never
   deletes an unrelated pre-existing `.old`. Rollback on failure.

### Tag/Asset Convention

- **Release tag:** `learning-media-{commit_short12}`
  e.g. `learning-media-07b527103e28`
- **Asset name:** `cogentrex-learning-media-{commit_short12}.tar.gz`
  e.g. `cogentrex-learning-media-07b527103e28.tar.gz`
- **Download URL:** `https://github.com/levalencia/cogentrex/releases/download/{tag}/{asset}`

The release asset for source commit `07b527103e28` was uploaded and downloaded
again for checksum and byte-size verification. Artifact status remains
`review-ready`; release distribution is not human learning-quality acceptance.

## Files

| File | Purpose |
|------|---------|
| `scripts/learning-media-release.py` | CLI tool (stdlib-only Python) |
| `backend/tests/unit/test_learning_media_release.py` | Comprehensive unit tests |
| `docs/plans/2026-09-09-learning-media-distribution.md` | This plan |
| `docs/visual-learning/release-manifest.json` | Pinned release URL, byte size, and SHA-256 |

## Limitations

- Each new media revision requires a newly generated archive, immutable release
  tag, and checked-in manifest bound to the catalog's source commit.
- No GitHub Actions workflow is included; release creation is manual or
  orchestrator-driven.
- The tool uses only Python stdlib (no `requests`, no `pip` dependencies).
- Maximum archive size is 2 GiB.
