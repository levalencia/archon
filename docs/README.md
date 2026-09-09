# Archon Documentation

Use this page as the learning map for Archon. The material moves from agent
fundamentals to implementation, operations, evidence, and advanced-role
preparation. Current status lives in the
[capability manifest](implementation/CAPABILITY-ACCEPTANCE.yaml) and its
[technical evidence ledger](IMPLEMENTATION-EVIDENCE.md).

---

## Learn

Start with the course and use visual material to build a mental model before
tracing implementation details.

| Doc | Purpose |
|-----|---------|
| [Course Home](course/README.md) | Module navigation and learning tracks |
| [Syllabus](course/syllabus.md) | Prerequisites, module sequence, learning objectives |
| [Concept Map](course/concept-map.md) | Dependency graph across all concepts |
| [Visual Learning Studio](visual-learning/README.md) | Interactive decks, audio, video, and study tools |

## Understand the architecture

Connect concepts to the real system.

| Doc | Purpose |
|-----|---------|
| [Architecture Diagrams](ARCHITECTURE-DIAGRAMS.md) | Visual system overview — control plane, data flow, and deployment topology |
| [Code Bookmarks](course/reference/code-bookmarks.md) | Exact source symbols behind the concepts |
| [Remaining Deferred Gaps](REMAINING-DEFERRED-GAPS.md) | What Archon deliberately does *not* implement or claim |

## Build and run

Exercise the same operational boundaries used by the project.

| Doc | Purpose |
|-----|---------|
| [CI, Pipelines & Local Run](CI-PIPELINES-AND-LOCAL-RUN.md) | Tests, Docker Compose services, and local commands |
| [DR Runbook](DR-RUNBOOK.md) | Backup, restore, health checks, and recovery practice |
| [Postmortem — Local Deployment](POSTMORTEM-LOCAL-DEPLOYMENT.md) | Lessons from the local deployment smoke |

## Prepare for advanced roles

Practice explaining what you built without exaggerating its evidence.

| Doc | Purpose |
|-----|---------|
| [Career Preparation Route](course/tracks/interview-preparation.md) | Short and deep ways to explain the architecture and trade-offs |
| [Architecture Answer Bank](INTERVIEW-ANSWER-BANK.md) | Evidence-backed answers to common system-design questions |
| [Practice Walkthrough](DEMO-SCRIPT.md) | A repeatable way to present and explain the running system |

## Verify your understanding

Check whether your explanation matches what the repository actually proves.

| Doc | Purpose |
|-----|---------|
| [Evidence Guide](EVIDENCE.md) | Human-readable overview and route into the evidence system |
| [Implementation Evidence](IMPLEMENTATION-EVIDENCE.md) | Detailed technical ledger for maintainers and auditors |
| [Capability Acceptance](implementation/CAPABILITY-ACCEPTANCE.yaml) | Canonical machine-readable capability status |

## Contribute / Reference

Architecture decisions, plans, and writing conventions.

| Doc | Purpose |
|-----|---------|
| [Documentation Guide](DOCUMENTATION-GUIDE.md) | Audience, status conventions, front-matter rules |
| [ADR: Local Production-Like Deployment](adr/0001-local-production-like-deployment.md) | Architecture decision record |
| [Skills + Project Instructions Architecture](architecture/skills-project-instructions.md) | Design of the skill/instruction subsystem |
| [Hybrid Agent Orchestration](architecture/hybrid-agent-orchestration.md) | Team pilot and verifier design |

## Historical

Superseded or archived documents kept for traceability.

<details>
<summary>Show historical planning, audit, and research documents</summary>

| Doc | Purpose |
|-----|---------|
| [Historical index](history/README.md) | Superseded plans, audits, research notes, and launch strategy |
| [Competitive Analysis](COMPETITIVE-ANALYSIS.md) | Framework comparison notes |

</details>

---

*This index does not invent status or counts. For current capability status,
defer to [Capability Acceptance](implementation/CAPABILITY-ACCEPTANCE.yaml) and
its supporting [Implementation Evidence](IMPLEMENTATION-EVIDENCE.md).*
