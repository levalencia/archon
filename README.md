<div align="center">

# 🏛️ Archon

### Production AI Agent Webapp

**ReAct reasoning · Multi-agent orchestration · RAG · Tools · Skills · Vision · Artifacts**
**Guardrails · PII Detection · Circuit Breakers · OpenTelemetry · 100% Local**

[![CI](https://github.com/levalencia/archon/actions/workflows/ci.yml/badge.svg)](https://github.com/levalencia/archon/actions)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-277%20passed-brightgreen.svg)]()
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

<img src="docs/mockup-archon-ui.html" alt="Archon UI" width="800">

*A complete AI agent system you can run locally with zero API keys.*

[Quick Start](#-quick-start) · [Features](#-features) · [Architecture](#-architecture) · [API Docs](#-api) · [Deploy](#-deploy)

</div>

---

## ⚡ Quick Start

```bash
# Clone
git clone https://github.com/levalencia/archon.git
cd archon

# Start infrastructure (PostgreSQL, Redis, Jaeger)
docker compose up -d

# Pull a local LLM
ollama pull llama3.1:8b
ollama pull llava:7b  # optional: for image analysis

# Backend
cd backend
uv sync --extra dev
cp .env.example .env  # defaults to Ollama
uv run uvicorn app.main:app --reload

# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

Open **http://localhost:3000** — start chatting. Zero API keys needed.

---

## 🎯 Features

| Feature | Description |
|---|---|
| 🧠 **ReAct Agent** | Think → Act → Observe reasoning loop with tool calling |
| 🤖 **Multi-Agent** | Coordinator + Planner + Retriever + Validator + Synthesizer |
| 📄 **RAG Pipeline** | Upload docs → chunk → embed → vector search → grounded answers |
| 🔧 **5 Built-in Tools** | Calculator, datetime, web search (DuckDuckGo), file reader, image gen |
| 📚 **Skills System** | Import skills from any GitHub repo, auto-match per query |
| 🎨 **Artifacts** | Claude-style artifact viewer: HTML, code, SVG, Mermaid rendered in iframe |
| 👁️ **Vision** | Upload images → auto-switch to llava for analysis |
| 🛡️ **Security** | PII detection, input/output guardrails, prompt injection blocking |
| ⚡ **Circuit Breaker** | CLOSED/OPEN/HALF_OPEN per provider, auto-recovery |
| 🚦 **Rate Limiter** | Redis sliding window, per-user limits |
| 🔐 **Auth** | JWT tokens + API keys, register/login |
| 📊 **Observability** | Structured logging, Prometheus metrics, trace waterfall |
| 🔄 **Provider Swappable** | Ollama, OpenAI, Anthropic, Azure Foundry — change in `.env` |
| 🐳 **100% Local** | Docker Compose: PostgreSQL + Redis + Jaeger + Ollama |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Svelte Frontend                     │
│  Chat · Artifacts · Trace · Dashboard · Settings     │
├──────────────────────┬──────────────────────────────┤
│    FastAPI Backend    │     Observability Layer       │
│                      │  structlog · Prometheus       │
│  ReAct Agent ◄──►    │  OTel Tracing · Cost Tracker  │
│  Multi-Agent         │  Correlation IDs              │
│  RAG Pipeline        ├──────────────────────────────┤
│  Tool Registry       │     Security Layer            │
│  Skills Engine       │  Guardrails · PII · Auth      │
│  Artifact Detector   │  Circuit Breaker · Rate Limit │
├──────────────────────┴──────────────────────────────┤
│              Infrastructure                          │
│  PostgreSQL (pgvector) · Redis · Jaeger · Ollama     │
└─────────────────────────────────────────────────────┘
```

**50 Python source files · 10 Svelte components · 277 tests · 30+ API endpoints**

---

## 🔌 API

All endpoints at `http://localhost:8000`:

| Method | Path | Description |
|---|---|---|
| POST | `/api/chat` | Send message, get agent response with tools + thinking |
| POST | `/api/chat/stream` | SSE streaming response |
| GET/POST | `/api/conversations` | List / create conversations |
| POST | `/api/documents/upload` | Upload and index a document (RAG) |
| POST | `/api/documents/query` | Query documents with RAG |
| GET/POST | `/api/skills` | List / create / import skills |
| POST | `/api/skills/import` | Import skill from GitHub repo |
| POST | `/api/security/pii-scan` | Scan text for PII |
| POST | `/api/security/guardrail` | Test guardrails |
| GET | `/api/admin/health` | Detailed health + uptime |
| GET | `/api/admin/metrics` | System metrics |
| GET | `/metrics` | Prometheus format metrics |
| POST | `/api/auth/register` | Register new user |
| POST | `/api/auth/login` | Login, get JWT token |

Full OpenAPI docs: `http://localhost:8000/docs`

---

## 🚀 Deploy

### Docker Compose (Production)
```bash
docker compose -f docker-compose.prod.yml up -d
```

### Kubernetes
```bash
helm install archon ./deploy/helm/archon \
  --set config.llmProvider=ollama \
  --set config.llmModel=llama3.1:8b
```

### Azure App Service
```bash
az webapp up --name archon --resource-group my-rg
```

---

## 🧪 Testing

```bash
cd backend
uv run pytest -m unit -q          # 277 tests, ~20s
uv run pytest -m security -v      # Security probe tests
uv run ruff check app/ tests/     # Lint
```

---

## 📦 Tech Stack

| Layer | Technology |
|---|---|
| Frontend | SvelteKit + Tailwind CSS |
| Backend | FastAPI + Python 3.11 |
| LLM | Ollama (llama3.1, llava) · OpenAI · Anthropic · Azure Foundry |
| Database | PostgreSQL + pgvector |
| Cache | Redis |
| Tracing | Jaeger + OpenTelemetry |
| Metrics | Prometheus + Grafana |
| Deploy | Docker Compose · Kubernetes · Helm |

---

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

1. Fork the repo
2. Create a feature branch
3. Write tests (RED → GREEN)
4. Submit a PR

---

## 📝 License

MIT — see [LICENSE](LICENSE) for details.

---

<div align="center">

Built by [Luis Valencia](https://github.com/levalencia) — Microsoft MVP · AI & Data Practice Lead

**Zero frameworks. Pure Python. Production-ready.**

</div>
