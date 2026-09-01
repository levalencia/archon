# Deployment safety checklist

## Before
- Verify the exact candidate commit, clean tree, CI status, configuration, and rollback path.
- Back up durable data and verify its checksum before recreating services.
- Render deployment configuration without printing secrets.

## Rollout
- Prefer in-place upgrades that preserve volumes and identities.
- Run schema migrations once and observe readiness, health, and restart counts.
- Stop on failed preflight or unhealthy dependencies; do not mask with mocks.

## Acceptance
- Test authenticated user-facing behavior, not only infrastructure health.
- Compare data counts and migration revision before and after.
- Record deployed commit, provider/model, limitations, and rollback evidence.
