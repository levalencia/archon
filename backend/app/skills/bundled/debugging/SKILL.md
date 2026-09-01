---
name: debugging
description: Diagnose failures using evidence and minimal hypotheses
version: 1.0.0
tags: [debugging, archon]
references: [references/checklist.md]
triggers: ['debug', 'traceback', 'failing']
negative_triggers: ['do not debug', 'ignore failure']
required_capability_ids: [capability.code.read]
context_cost: 56
---
Reproduce, isolate, explain root cause, fix, and verify.
