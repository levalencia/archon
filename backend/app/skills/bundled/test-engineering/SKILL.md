---
name: test-engineering
description: Design and run focused automated tests
version: 1.0.0
tags: [test-engineering, archon]
references: [references/checklist.md]
triggers: ['write tests', 'run tests', 'tdd']
negative_triggers: ['do not test', 'skip tests']
required_capability_ids: [capability.test.run]
context_cost: 73
---
Start with a failing focused test, implement, then run regression checks.
