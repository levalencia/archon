---
name: api-design
description: Design stable typed API contracts
version: 1.0.0
tags: [api-design, archon]
references: [references/checklist.md]
triggers: ['api design', 'endpoint contract', 'rest api']
negative_triggers: ['do not change api', 'no api']
required_capability_ids: [capability.api.design]
context_cost: 77
---
Prefer bounded typed contracts, explicit errors, and backwards compatibility.
