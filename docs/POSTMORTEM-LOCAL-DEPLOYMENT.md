# Postmortem: Making the local deployment evidence trustworthy

- **Date:** 2026-08-26–27
- **Severity:** Development/release-evidence blocker
- **Customer impact:** None; no public environment existed
- **Status:** Resolved for the verified local target

## Summary

The first production-like local deployment and DR attempts exposed four independent gaps that unit tests and static manifests had not proven:

1. the native Apple ARM backend image exited with `SIGILL` while importing `cryptography`;
2. readiness described OTEL as configured even when SDK/export dependencies were absent;
3. PostgreSQL document ingestion used a NUL byte in an advisory-lock text key;
4. temporary-file templates that worked on GNU systems produced predictable literal names on macOS.

The team stopped treating container startup or source presence as evidence, reproduced each failure, added tests, and reran complete local smokes.

## Timeline

1. Static deployment tests passed.
2. The first Compose smoke reached PostgreSQL/Redis health but backend remained unhealthy.
3. A retained diagnostic run showed repeated migrations and no Uvicorn startup.
4. Direct image import returned exit code 132, confirming native ARM `SIGILL`.
5. Backend was explicitly pinned to `linux/amd64`; Compose smoke then passed.
6. Security review found OTEL dependencies absent and readiness based on object existence.
7. SDK/exporter dependencies, active-state readiness, digest pins, and real `agent.run` collector verification were added.
8. The first DR run failed at document ingest with PostgreSQL `invalid byte sequence ... 0x00`.
9. The advisory-lock key changed from NUL concatenation to canonical JSON tuple serialization.
10. Later DR harness failures exposed non-portable `mktemp` and `psql -c` variable assumptions; both were corrected.
11. Clean backup/destroy/restore passed with exact evidence verification.

## Root causes

### 1. Architecture-specific native dependency failure

The existing backend smoke already knew that an amd64 image was required on the Mac, but the new Compose target did not encode that boundary. Native package import failed before application logging initialized.

### 2. Configuration mistaken for active telemetry

`OTLPExporter` could fall back to an in-memory tracer when OpenTelemetry packages were missing. Readiness checked only that an exporter object existed, not that the real SDK/provider was active. The smoke checked collector health, not an exported span.

### 3. SQLite/PostgreSQL behavioral gap

Document quota locking used `owner_id + "\0" + project_id` as a PostgreSQL `text` parameter. PostgreSQL rejects NUL in UTF-8 text. SQLite-focused ingestion tests never traversed that PostgreSQL-only branch.

### 4. Platform-specific shell assumptions

BSD/macOS `mktemp` requires the `X` template at the end. Templates with `.env`/`.json` suffixes and `mktemp -u` created predictable or unsafe paths. The original static tests checked secret permissions but not macOS template semantics.

## Resolution

- Set backend Compose platform to `linux/amd64` by default and document why.
- Pin all target images by immutable digest and run `uv sync --frozen`.
- Add production OpenTelemetry SDK and OTLP gRPC exporter dependencies.
- Expose `is_active`, fail readiness when configured telemetry is inactive, flush on shutdown, and verify `agent.run` in collector output.
- Serialize advisory-lock scope as canonical JSON `[owner_id, project_id]`, eliminating NUL and separator collisions.
- Use secure suffix-free macOS-compatible `mktemp` files/directories and mode `0600`.
- Add stage markers, checksum verification, clean-target refusal and exact API/SQL DR checks.

## Verification

- Final integrated acceptance at `60a8d6a`: 1,034 backend tests, 86.27% coverage, frontend and Docker gates green.
- Local Compose smoke: migrations at revision 08, Redis readiness, auth, metrics and OTEL span observed.
- DR: backup 0.69 s, observed clean restore-to-ready 24.787 s, zero selected-record differences at snapshot, exact restored evidence.
- Regression: document lock-key unit test plus real PostgreSQL document ingest during DR.

## What went well

- Failures were reproduced with retained containers before changing code.
- Secrets were generated ephemerally and not printed.
- Each discovered production-path issue became a test or runtime assertion.
- The final evidence distinguishes local verification from deployment.

## What could improve

- New Compose paths should have reused the existing architecture constraint immediately.
- Readiness reviews should ask “is the dependency active?” rather than “is an object configured?”
- PostgreSQL-specific code needs routine real-PostgreSQL probes, not only SQLite suites.
- Shell portability checks should include macOS semantics when the authoritative host is macOS.

## Prevention actions

| Action | Status |
|---|---|
| Immutable image digests and frozen dependency sync | Done |
| Architecture encoded in verified Compose | Done |
| Real telemetry export assertion | Done |
| PostgreSQL ingestion exercised by DR | Done |
| macOS-safe temp creation and static regressions | Done |
| Full final acceptance after docs integration | Pending S7.5 |
| Public/cloud rollout checklist | Deferred until authorized |

## Blameless conclusion

The defects came from evidence gaps across architecture, optional dependencies, database dialects and shell platforms—not from one person. The corrective principle is to prefer end-to-end proof over inferred readiness.
