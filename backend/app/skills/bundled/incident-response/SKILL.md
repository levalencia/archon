---
name: incident-response
description: Triage and contain production incidents
version: 1.0.0
tags: [incident-response, archon]
references: [references/checklist.md]
triggers: ['incident', 'outage', 'production failure']
negative_triggers: ['not an incident', 'ignore outage']
required_capability_ids: [capability.incident.respond]
context_cost: 79
---
Prioritize safety, containment, evidence preservation, recovery, and follow-up.
