# Database migration checklist

## Design
- Keep ORM models and Alembic schema changes in the same change set.
- Use scoped foreign keys and uniqueness constraints to enforce tenant boundaries.
- Prefer append-only revisions for auditable configuration and provenance.

## Safety
- Provide upgrade and downgrade paths for SQLite tests and production PostgreSQL.
- Avoid destructive rewrites when an additive migration and backfill are sufficient.
- Make concurrent inserts deterministic with constraints and conflict handling.

## Verification
- Upgrade from the previous real revision, inspect constraints, and run downgrade/upgrade.
- Test restart persistence, cross-owner rejection, immutable rows, and duplicate handling.
- Back up production data and compare counts before any deployment migration.
