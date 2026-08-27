# Idempotency

**Status:** partial, implemented at selected persistence boundaries

## Definition
An operation is idempotent when repeating the same logical request does not create additional effects beyond the first successful application. Idempotency is essential before retrying side effects.

## Archon implementation
`RunRepository.ensure_run` uses conflict-safe insertion for a stable `run_id`; concurrent child ensures validate immutable lineage. Terminal updates are status/completion guarded, so a second finalization cannot overwrite the first. Fork checkpoints use deterministic UUID5 identity for owner/run/sequence and uniqueness constraints; Redis rate-limit members deliberately use unique IDs because each admitted request must count separately.

## Boundaries
Idempotent run creation does not make arbitrary tool/network calls idempotent. The runtime lacks a universal request idempotency-key ledger. A rejected duplicate terminal event raises rather than silently succeeding—state is protected, while API retry semantics remain explicit.

## Evidence
`backend/tests/unit/test_run_ledger.py::test_finalize_is_idempotent_and_cannot_overwrite_terminal_run`, `backend/tests/unit/test_run_lineage.py::test_concurrent_child_ensures_are_idempotent_and_parent_delete_is_restricted`, and fork integration tests.

## Interview prompt
“Place stable operation identity and atomic uniqueness before retries; protect each side effect independently.”
