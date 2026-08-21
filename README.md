# Archon — Production AI Agent Webapp

> Enterprise AI Research & Operations Assistant
> Perplexity meets ChatGPT meets audit dashboard

**Built by:** Luis Valencia — Microsoft MVP | AI & Data Practice Lead at element61
**Status:** Planning → Phase 0

## What is Archon?

A production-grade, multi-agent AI assistant that demonstrates every pattern a Founding AI Engineer needs: ReAct reasoning loops, encrypted memory, PII detection, circuit breakers, distributed rate limiters, RAG pipelines, multi-agent orchestration, OpenTelemetry observability, and evaluation harness — all deployed on Azure.

This is not a tutorial. This is a working webapp that proves I can build production AI agent systems.

## Architecture

```
Svelte Frontend (chat + trace viewer + security demo + admin)
    ↓ REST + SSE
FastAPI API Gateway (auth, rate limiter, CORS, correlation IDs)
    ↓
Agent Orchestrator (Coordinator + 4 specialist agents)
    ↓
Cross-cutting (circuit breaker, tool registry, memory, audit)
    ↓
Infrastructure (PostgreSQL + Redis + pgvector + Azure Blob)
```

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Frontend | SvelteKit + Tailwind | Professional chat UI (Claude/Perplexity style) |
| Backend | FastAPI + Python 3.11 | Async, typed, production-proven |
| LLM | Azure AI Foundry (Claude/GPT) | Vendor-neutral via Protocol adapters |
| Database | PostgreSQL + pgvector | Memory + vector search in one DB |
| Cache/State | Redis | Rate limiting, circuit breaker state, sessions |
| Observability | OpenTelemetry + Jaeger | Distributed tracing with PII scrubbing |
| Evaluation | Promptfoo + custom harness | Quality gates in CI |
| Deploy | Azure App Service → Container Apps → K8s | Progressive deployment |

## Development Phases (12 weeks)

| Phase | Week | What |
|---|---|---|
| 0 | 1 | Scaffold: monorepo, Docker Compose, CI/CD, Makefile |
| 1 | 2-3 | Core chat: ReAct agent + Svelte UI with SSE streaming |
| 2 | 4 | Security: PII detection, guardrails, sandboxing, permissions |
| 3 | 5-6 | RAG: upload → chunk → embed → pgvector → answer with citations |
| 4 | 7-8 | Multi-agent: Coordinator + Planner + Retriever + Validator + Synthesizer |
| 5 | 9 | Observability: OpenTelemetry, Jaeger, cost tracking |
| 6 | 10 | Advanced memory: tiered, context compression, encrypted |
| 7 | 11 | Eval harness: batch eval, quality gates, regression detection |
| 8 | 12 | Deploy: Azure App Service → Container Apps → K8s |

## Documentation

- [Full Development Plan](docs/PLAN.md) — 910 lines, phase-by-phase with course concept mapping
- [God Mode Skill Additions](docs/GOD-MODE-ADDITIONS.md) — 1,091 lines, patterns from 2,404-skill vault
- [Pocock Engineering Disciplines](docs/POCOCK-SKILLS-ADDITIONS.md) — 622 lines, how to work (TDD, code review, domain modeling)

## Related

- **Article Series:** [production-ai-agents](https://github.com/levalencia/production-ai-agents) — 41-article "From Prompt to Production" series with runnable code
- **Course Notes:** AIAMastery (30 days) + Advanced Architectures (90 lessons) — gap registry with 27 documented gaps between course claims and code reality

## Quick Start

```bash
# Coming in Phase 0
git clone https://github.com/levalencia/archon.git
cd archon
make dev  # Docker Compose: PostgreSQL + Redis + Jaeger + backend + frontend
```

## License

MIT
