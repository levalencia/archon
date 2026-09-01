---
name: documentation
description: Create precise technical documentation
version: 1.0.0
tags: [documentation, archon]
references: [references/checklist.md]
triggers: ['documentation', 'write docs', 'readme']
negative_triggers: ['do not document', 'skip docs']
required_capability_ids: [capability.docs.write]
context_cost: 68
---
Document behavior, contracts, examples, and operational constraints.
