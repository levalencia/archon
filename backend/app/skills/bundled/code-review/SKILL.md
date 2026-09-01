---
name: code-review
description: Review code for correctness, security, and maintainability
version: 1.0.0
tags: [code-review, archon]
references: [references/checklist.md]
triggers: ['code review', 'review python', 'review code']
negative_triggers: ['do not review', 'skip review']
required_capability_ids: [capability.code.read]
context_cost: 80
---
Inspect changes systematically; report evidence, severity, and actionable fixes.
