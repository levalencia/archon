# Debugging checklist

## Reproduce
- Record the exact command, environment, revision, and observed output.
- Reduce to the smallest failing test without changing production behavior.

## Diagnose
- Follow data through the real runtime path; do not infer wiring from class existence.
- Distinguish root cause from symptom, test flake, environment drift, and stale fixtures.
- Use logs and traces without exposing secrets or private payloads.

## Fix and verify
- Add a regression test that fails before the fix.
- Apply the smallest complete correction at the owning layer.
- Run focused tests, adjacent regression tests, and the project gate.
