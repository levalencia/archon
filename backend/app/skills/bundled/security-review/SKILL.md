---
name: security-review
description: Threat-model and review security boundaries
version: 1.0.0
tags: [security-review, archon]
references: [references/checklist.md]
triggers: ['security review', 'threat model', 'vulnerability']
negative_triggers: ['skip security', 'do not audit']
required_capability_ids: [capability.security.read]
context_cost: 83
---
Identify trust boundaries, fail closed, and verify authorization before disclosure.
