# Video 01 Approval and Replacement Incident

Date identified: 2026-09-18

## User-approved artifact

- Catalog ID: `code-first-video-01`
- Project: `video-01-main-lifespan-oriented-v3`
- File: `renders/video-01-main-lifespan-oriented-v3.mp4`
- Duration: 461.466667 seconds
- Size: 32,821,492 bytes
- SHA-256: `0bec4e01bad0c7718a9afca3522f21f126edc3591bdbd1a8e5cab883790f1eeb`
- Review status: revised Video 1; established production grammar; pronunciation correction for “main dot P Y”; strict/render/frame checks passed.

## Replacement that reached the public development environment

- Project: `main-lifespan-composition-root`
- Duration: 492.000 seconds
- Size: 32,495,578 bytes
- SHA-256: `af2dec35a18fc8ccc3200f36d56626d815ca0d589efbe08c27be02b8c9d2f438`
- Generated: 2026-09-15
- First immutable release containing it: `learning-media-1511aee380a4`

## Root cause

The architecture-first expansion regenerated Videos 1–20. Its Video 1 project used a new spec and composition, but reused both the stable catalog ID `code-first-video-01` and the path `published/code-first-series/code-first-video-01/lesson.mp4`. That replaced the previously reviewed V3 instead of publishing a separately versioned candidate.

The Videos 1–4 review checklist recorded the original Video 1 duration as 461.5 seconds and stated that all gates and a reviewer verdict were required before generation. The checklist remained unchecked, with reviewer/date/verdict blank. The subsequent pipeline treated technical render PASS as sufficient for catalog publication. This violated the intended human-acceptance gate.

The Azure rich-media wave did not create this replacement: it verified that all seven pre-existing pack entries were unchanged before adding Azure. It therefore preserved the already-wrong Video 1 from the previous immutable release.

## Corrective action

1. Restore the exact approved V3 bytes; do not regenerate them.
2. Preserve the replaced 492-second artifact in an incident backup.
3. Add `published/media-approvals.json` with the approved artifact checksum.
4. Make release packaging fail closed when an approved catalog artifact checksum differs from the ledger.
5. Make Azure deployment compare the installed media source revision with the repository release manifest instead of treating the ownership marker as proof that the latest release is installed.

## Limitation

The approval ledger prevents silent checksum replacement during packaging. It does not replace human review of new candidate revisions. A new Video 01 revision must use a new candidate identity until Luis explicitly approves replacing the current approved checksum.
