# Contextual Learning Tutor removal — 2026-09-17

## Decision

The contextual Learning Tutor chat and its dedicated retrieval/persistence stack were removed from the candidate source tree. Visual Learning and published learning media remain.

## Removed product surface

- `/api/learning-tutor` routes and SSE protocol;
- `backend/app/learning_tutor/` context, workflow, repository, indexer, web supplement, source collectors, and evaluation code;
- Tutor corpus sync and benchmark scripts/dataset;
- Tutor ORM rows for sources, chunks, sessions, and turns;
- Tutor config and Compose/provider-env mappings;
- `LearningTutorPanel`, its API client, session UI, and Tutor-only diagram renderer;
- Tutor-specific unit/integration/browser tests;
- contextual Tutor capability acceptance claim.

## Database removal

Forward migration `20260917_24` drops, in foreign-key order:

1. `learning_tutor_turns`;
2. `learning_tutor_sessions`;
3. `learning_chunks`;
4. `learning_sources`.

Its downgrade recreates the revision-23 schema. Historical migration `20260912_23` remains in the Alembic chain for deployed-database compatibility.

The migration is implemented and passes a SQLite upgrade → downgrade → upgrade round trip. It has **not** been applied to the retained PostgreSQL database because this branch is not merged or deployed and the retained backend still runs the old Tutor-aware code.

## Preserved Visual Learning

The following remain intact:

- `/learn` and all eight Studio views;
- Visual Learning manifest and schemas;
- searchable 299-term glossary;
- roadmap, stories, architecture, and evidence views;
- presentations, diagrams, infographics, mind maps, flashcards, quizzes, and study guides;
- audio/video players, transcripts, captions, source links, media catalog, signed delivery, and external published media library;
- all Visual Learning/media build and release scripts.

## Verification

- Tutor-removal source/route/ORM contract: PASS.
- Migration 23 → 24 → 23 → 24 contract: PASS.
- Frontend Svelte check: 0 errors, 0 warnings.
- Frontend Vitest: 80 passed.
- Visual Learning Playwright: 14 passed.
- Vocabulary generator check: 299 terms current.
- Visual Learning generator check: 67 concepts / 16 modules current.
- Course documentation validation: PASS.

Full clean-tree backend acceptance is recorded separately after commit.

## Boundaries

No push, merge, deployment, or retained-database mutation was performed. Historical Tutor evidence remains available as an audit record but is not a current capability claim.
