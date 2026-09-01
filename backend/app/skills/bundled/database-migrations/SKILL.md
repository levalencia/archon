---
name: database-migrations
description: Design reversible and safe database migrations
version: 1.0.0
tags: [database-migrations, archon]
references: [references/checklist.md]
triggers: ['database migration', 'schema migration', 'alembic']
negative_triggers: ['do not migrate', 'no schema changes']
required_capability_ids: [capability.database.migrate]
context_cost: 68
---
Keep schema and models aligned; provide upgrade and downgrade paths.
