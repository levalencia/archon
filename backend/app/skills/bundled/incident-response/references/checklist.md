# Incident response checklist

## Triage
- Establish impact, affected users, start time, current symptoms, and owner.
- Preserve logs, traces, correlation IDs, and relevant immutable revisions.

## Contain and recover
- Prefer reversible containment; avoid destructive cleanup before evidence capture.
- Revoke compromised access, isolate failing components, and verify dependencies.
- Restore from a verified backup or known-good revision when required.

## Close
- Validate user-facing recovery and data integrity.
- Document timeline, root cause, contributing controls, and follow-up owners.
- Add tests or alerts that detect the same failure earlier.
