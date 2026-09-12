# Cogentrex Repository-Wide Rebrand Plan

## Goal

Replace the previous product identity with Cogentrex across tracked source, tests, documentation, Visual Learning, runtime identifiers, deployment definitions, and brand assets. Rebuild the approved code-walkthrough pilot with the Cogentrex logo and tagline: “Build agents you can explain.”

## Scope boundary

- Work only in branch/worktree `feat/cogentrex-rebrand` at `/private/tmp/cogentrex-rebrand`.
- Do not modify `/Users/luisvalencia/Documents/personal/cogentrex`.
- Do not rename or push either GitHub repository, deploy services, edit protected env files, or replace the retained media library without separate authorization.
- The existing `levalencia/cogentrex` remote belongs to the older Cogentrex project; repository URL changes in this branch are future-state references until Luis authorizes the external repository transition.

## Breaking-change posture

The user requires zero remaining references to the previous product identity. Therefore this is a clean namespace cutover rather than a dual-brand compatibility release:

- Legacy product-prefixed environment variables become `COGENTREX_*`.
- The legacy project-instruction dot-directory becomes `.cogentrex/`.
- schema, metric, trace, Redis, export, cookie, package, image, state-directory, and cryptographic domain namespaces become Cogentrex.
- Existing ignored env files, local browser storage, encrypted local data, Redis keys, API keys, and previously published media are not silently migrated.
- Historical migration source is renamed for fresh installs. Existing local state requires an explicit backup-and-recreate cutover rather than a silent compatibility layer.

## Pieces

1. Inventory and classify tracked references and path names.
2. Reconstruct approved Cogentrex SVG assets and favicon variants.
3. Add regression tests for product identity and zero residual references.
4. Rename frontend theme, storage keys, user-facing text, metadata, and static learning filename.
5. Rename backend application identity, env prefix, protocol/schema namespaces, metrics, trace attributes, Redis keys, paths, and package metadata.
6. Rename Compose, Docker, scripts, Helm/Kubernetes, local state, image, container, and database identifiers.
7. Rename documentation, diagrams, course material, history files, plans, schemas, and source URLs.
8. Regenerate Visual Learning derived JSON from renamed source inputs.
9. Rebrand and rerender the approved code-walkthrough pilot using the new logo and tagline.
10. Run a case-insensitive tracked-content and tracked-filename scan for the previous identity, then run focused and full repository gates.

## Verification

- A case-insensitive scan for the previous identity over tracked text returns no matches.
- `git ls-files '*[Aa][Rr][Cc][Hh][Oo][Nn]*'` returns no paths.
- Logo SVGs parse, provide accessible titles, and render in dark/light/favicons.
- Frontend check, tests, build, and focused Playwright branding tests pass.
- Backend tests and lint pass.
- Visual Learning generation/checks pass using Cogentrex schema and filenames.
- Compose/config tests assert only `COGENTREX_*` names.
- Pilot HyperFrames check passes, rendered frames show the Cogentrex mark, and MP4 codec/duration checks pass.
- Full `make test`, `make lint`, and `make fmt` run before handoff.
