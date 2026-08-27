# Online encrypted-memory key rotation

This procedure rotates Archon's scoped-memory encryption key without exporting plaintext.
Key material must come from the deployment secret store and must never be committed, logged,
or included in API requests.

## Hard safety boundary

The durable `memory_key_state` fence is enforced only by key-generation-aware Archon binaries.
**Drain every pre-`20260827_11` writer before activating a new key version.** A binary that predates
the fence cannot inspect `memory_key_state` and can otherwise create old-version ciphertext after a
retirement check.

`assert_key_retirable(..., legacy_writers_drained=True)` deliberately requires an explicit operator
attestation. The attestation is invalid unless the drain and inventory checks below have completed.

## Rotation sequence

1. Apply Alembic migration `20260827_11`.
2. Deploy the generation-aware binary everywhere with the current active version and the complete
   current keyring. Do not change the active version yet.
3. Drain and terminate every older writer. Verify the process/container inventory contains no
   pre-fence build. Prevent autoscaling from an old image.
4. Add the new key to `ARCHON_MEMORY_KEYRING_JSON` on every new worker, keeping the old active
   version. Restart and verify startup succeeds.
5. Set `ARCHON_MEMORY_ACTIVE_KEY_VERSION` to the new, monotonically higher version. The first new
   worker atomically advances `memory_key_state`; stale generation-aware writers then fail closed on
   mutations with `memory_key_generation_mismatch`.
6. Repeatedly call `POST /api/memory/rotation?project_id=...` for each owner/project scope until the
   response reports `remaining: 0`. Calls are bounded, transactional, resumable, authenticated, and
   rate-limited.
7. Confirm `GET /api/memory/rotation?project_id=...` reports only the active version for every scope.
8. Run the global retirement precheck with `legacy_writers_drained=True`. It locks the same global
   generation row used by writes and rejects retirement while any ciphertext references the old
   version.
9. Remove the old key from the secret-store keyring, restart all workers, and verify startup's global
   referenced-version validation succeeds.

## Interruption and rollback

- Before step 5, revert configuration to the original active version.
- After step 5, do not downgrade the active version. Keep both keys configured, fix the deployment,
  and resume bounded re-encryption.
- A failed batch rolls back in full. Re-running it selects the remaining old-version rows.
- Never remove an old key merely because one scope reports complete; retirement is global.

## Evidence to retain

Retain only deployment/build inventory, active version/generation, per-version row counts, batch
counts, and timestamps. Do not retain key material, decrypted facts, ciphertext dumps, or request
payloads.
