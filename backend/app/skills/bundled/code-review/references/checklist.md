# Code review checklist

## Correctness
- Trace the request from public entry point to durable side effects.
- Check error paths, retries, cancellation, concurrency, and cleanup.
- Look for behavior claimed by docs or tests but absent from runtime wiring.

## Security
- Identify trust boundaries, owner/project filters, secret handling, and permission checks.
- Test path traversal, stale authorization, race conditions, and fail-open defaults.

## Evidence
- Classify findings by severity and cite exact files and lines.
- Reproduce high-severity findings with a focused test.
- Approve only the exact reviewed commit after focused and regression gates pass.
