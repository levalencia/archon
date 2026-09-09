# Archon Documentation

Find the shortest route to the question you are trying to answer. Archon is a
local Agent Reliability Workbench; current status lives in the
[capability manifest](implementation/CAPABILITY-ACCEPTANCE.yaml) and its
[technical evidence ledger](IMPLEMENTATION-EVIDENCE.md).

---

## Understand

Start here to learn what Archon is and how it works.

| Doc | Purpose |
|-----|---------|
| [Architecture Diagrams](ARCHITECTURE-DIAGRAMS.md) | Visual system overview — control plane, data flow, deployment topology |
| [Interview Answer Bank](INTERVIEW-ANSWER-BANK.md) | Concise, evidence-backed explanations of every major design decision |
| [Remaining Deferred Gaps](REMAINING-DEFERRED-GAPS.md) | What Archon deliberately does *not* claim, and why |

## Run

Get the system running locally and operate it day-to-day.

| Doc | Purpose |
|-----|---------|
| [CI, Pipelines & Local Run](CI-PIPELINES-AND-LOCAL-RUN.md) | GitHub Actions workflow, Docker Compose services, `make` targets |
| [DR Runbook](DR-RUNBOOK.md) | Backup, restore, health checks, measured RTO/RPO |
| [Demo Script](DEMO-SCRIPT.md) | 3–5 minute walkthrough for live or recorded demos |
| [Postmortem — Local Deployment](POSTMORTEM-LOCAL-DEPLOYMENT.md) | Lessons from the local deployment smoke |

## Learn

Structured course material for onboarding, interview prep, or deep study.

| Doc | Purpose |
|-----|---------|
| [Course Home](course/README.md) | Module navigation and learning tracks |
| [Syllabus](course/syllabus.md) | Prerequisites, module sequence, learning objectives |
| [Concept Map](course/concept-map.md) | Dependency graph across all concepts |
| [Visual Learning Studio](visual-learning/README.md) | Interactive decks, audio, video, and study tools |

## Evidence

Proof of what works, how it was tested, and what the boundaries are.

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
| [Implementation Status (superseded)](IMPLEMENTATION-STATUS.md) | Pre-audit status snapshot — replaced by Implementation Evidence |
| [PLAN.md](PLAN.md) | Original project plan |
| [Evidence-First Roadmap V2](ARCHON-EVIDENCE-FIRST-ROADMAP-V2.md) | Historical implementation sequence and acceptance design |
| [GPT-5.6 Re-Audit](ARCHON-GPT56-REAUDIT-2026-08-25.md) | Historical architecture and maturity audit |
| [Feature & Course Audit V2](FEATURE-AND-COURSE-AUDIT-V2.md) | Earlier audit that preceded the current evidence matrix |
| [God Mode Additions](GOD-MODE-ADDITIONS.md) | Historical architecture research notes |
| [Pocock Skills Additions](POCOCK-SKILLS-ADDITIONS.md) | Historical engineering-practice research notes |
| [Competitive Analysis](COMPETITIVE-ANALYSIS.md) | Framework comparison notes |
| [Launch Playbook](LAUNCH-PLAYBOOK.md) | Aspirational launch research; not deployment evidence |

</details>

---

*This index does not invent status or counts. For current capability status,
defer to [Capability Acceptance](implementation/CAPABILITY-ACCEPTANCE.yaml) and
its supporting [Implementation Evidence](IMPLEMENTATION-EVIDENCE.md).*
