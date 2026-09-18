# Required Email and Sole Admin Plan

Status: Approved default — controlled bootstrap plus existing admin surfaces

## Goal

Require a normalized unique email for every new registration, remove username-based privilege assignment, enforce at most one administrator in the database, promote the existing Luis account once through a server-side command, and hide existing admin-only navigation from normal users while preserving backend `403` enforcement.

## Data compatibility

- Preserve all existing users, runs, conversations, and evidence.
- Convert legacy empty email strings to `NULL`.
- New registrations require a syntactically valid email.
- Normalize new emails with `strip().casefold()` before persistence.
- Enforce case-insensitive uniqueness for non-null emails.
- Enforce at most one row with `is_admin = 1`.

## Security invariants

- Production registration never grants admin status; the deprecated explicit test hook defaults empty and is not configured by deployment.
- Deployed authorization never derives from username.
- No admin email is hardcoded into source.
- Sole-admin promotion is unavailable over HTTP.
- The promotion command fails unless exactly one normalized email matches.
- JWT/API-key requests re-read the current database role.
- UI visibility is not the authorization boundary; backend dependencies remain authoritative.

## TDD sequence

1. Add RED migration/schema contracts for nullable legacy email, normalized unique email, and sole-admin uniqueness.
2. Add RED API contracts for required valid email, case-insensitive duplicate conflict, and no username auto-admin.
3. Add RED repository/CLI contracts for exactly-one admin promotion.
4. Implement migration, repository normalization, promotion CLI, and API error semantics.
5. Add RED frontend tests for required email and admin-only navigation.
6. Implement current-user state and conditional admin navigation.
7. Run focused security/integration tests, full backend/frontend gates, migration upgrade/downgrade checks, then PR to protected `dev`.
8. After deployment, verify the existing normalized email has one row, run the promotion command once, and prove exactly one admin plus normal-user `403` behavior.

## Explicit deferrals

- Microsoft Entra login.
- Email delivery/verification.
- A new Admin Control Center.
- Production deployment.
