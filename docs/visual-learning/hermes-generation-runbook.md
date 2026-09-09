# Hermes Learning Media Runbook

This runbook creates reviewed English learning artifacts without making Hermes a runtime dependency of Archon.

## 1. Prepare

- Work from a feature branch with reviewed canonical sources.
- Never include `.env`, credentials, profile memory, private course text, cookies, or session transcripts.
- Keep generated binaries outside Git under `../archon-learning-media/`.

## 2. Build the deterministic pilot

```bash
backend/.venv/bin/python scripts/build-learning-pilot.py \
  --output ../archon-learning-media \
  --audio ../archon-learning-media/candidates/request-lifecycle/request-lifecycle-english.mp3 \
  --video ../archon-learning-media/candidates/request-lifecycle/request-lifecycle-video-final.mp4
```

The builder validates allowlisted source paths, generates structured English artifacts, produces standalone HTML/SVG, records SHA-256 checksums, and writes `catalog.json`.

Build or refresh the remaining source-authored packs after the request-lifecycle
pilot so the catalog retains all six entries:

```bash
cd backend
uv run python ../scripts/build-learning-packs.py \
  --output ../../archon-learning-media \
  --media-root ../../archon-learning-media/generated-media
```

The generalized builder reads `docs/visual-learning/packs/*.json`, verifies
that every cited path belongs to the pack allowlist and exists, validates every
structured artifact against the repository schemas, and keeps every generated
catalog entry at `review-ready`.

## 3. Audio

Generate reviewed English TTS segments, concatenate and normalize them with FFmpeg, then verify codec, duration, channels, clipping, silence, and transcript correspondence with FFprobe and listening review.

## 4. Video

The HyperFrames source is under `spikes/learning-media-video/`.

```bash
cd spikes/learning-media-video
npm run check
npx --yes hyperframes@0.8.27 render --quality high \
  --output ../../archon-learning-media/candidates/request-lifecycle/request-lifecycle-video-final.mp4
```

Verify the final stream metadata with FFprobe and inspect representative frames. A successful render is not publication approval by itself.

The remaining five pinned HyperFrames projects live under
`spikes/learning-media-videos/<pack-id>/`. Regenerate their compositions from
the same source-authored pack data, then run the pinned check and render in each
project:

```bash
python3 scripts/build-learning-video-projects.py
cd spikes/learning-media-videos/<pack-id>
npm run check
npx --yes hyperframes@0.8.27 render --quality high \
  --output ../../../archon-learning-media/generated-media/<pack-id>/<pack-id>.mp4
```

Only rerun `build-learning-packs.py --media-root ...` after FFprobe confirms
H.264 video, AAC audio, 1920×1080 dimensions, expected duration, and nonzero
size. This final build copies verified media into the read-only published tree
and refreshes checksums at catalog level.

## 5. Review

Reject any artifact that invents capability, deployment, provider, benchmark, or security evidence. Accuracy, evidence boundaries, source traceability, accessibility, and English clarity are hard gates.

## 6. Local runtime

Enable the read-only catalog only for an authorized local deployment:

```text
ARCHON_LEARNING_MEDIA_ENABLED=true
ARCHON_LEARNING_MEDIA_HOST_DIR=../archon-learning-media
```

Use the canonical local-stack script. Do not expose another host port. Verify stack status, readiness, authenticated catalog access, byte-range playback, and browser behavior.

## Evidence levels

- Schema/unit pass: deterministic contract only.
- TTS/HyperFrames output: real media generation.
- Human review: learning quality acceptance.
- Local browser verification: locally available feature.
- None of these establish public deployment.

## 7. Distribute rich media

After all packs pass the technical gates, package the review-ready library for
GitHub Release distribution. Distribution does not change artifact status to
`published` or replace Luis's learning-quality review.

```bash
python3 scripts/learning-media-release.py package \
  --library ../archon-learning-media \
  --output dist/archon-learning-media.tar.gz \
  --manifest-output docs/visual-learning/release-manifest.json
```

This creates a deterministic, checksummed archive. Commit the updated manifest
and upload the archive as a GitHub Release asset tagged
`learning-media-{commit_short12}`.

Recipients install with:

```bash
python3 scripts/learning-media-release.py install \
  --target ../archon-learning-media \
  --manifest docs/visual-learning/release-manifest.json
# or offline:
python3 scripts/learning-media-release.py install \
  --target ../archon-learning-media \
  --archive dist/archon-learning-media.tar.gz \
  --manifest docs/visual-learning/release-manifest.json
```

Install before the first managed-stack start. Environment generation validates
the sibling ownership marker and catalog shape, enables learning media when the
library is present, and leaves it disabled when the library is absent. Backend
startup performs the complete artifact checksum validation.

See `docs/visual-learning/README.md` § "Base vs. Rich behavior" for details.
