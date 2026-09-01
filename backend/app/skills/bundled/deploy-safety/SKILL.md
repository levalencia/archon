---
name: deploy-safety
description: Plan safe, reversible deployments
version: 1.0.0
tags: [deploy-safety, archon]
references: [references/checklist.md]
triggers: ['deploy', 'release', 'rollout']
negative_triggers: ['do not deploy', 'no release']
required_capability_ids: [capability.deploy.execute]
context_cost: 75
---
Verify prerequisites, stage rollout, monitor health, and preserve rollback.
