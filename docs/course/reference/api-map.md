# API map

> **Generated snapshot boundary:** manually derived from FastAPI decorators and router prefixes at revision `3577b00`. It is a navigation index, not a stable public API contract. Runtime OpenAPI from the checked-out application is authoritative for request/response schemas. Recheck [`create_app`](../../../backend/app/main.py) after route changes.

Authentication and owner scope vary by router and endpoint. Read dependencies in the linked route before calling it; never infer public access from this table.

| Area | Methods and paths | Route source | Notes |
|---|---|---|---|
| Core probes | `GET /healthz`; `GET /readyz`; `GET /metrics` | [`main.py`](../../../backend/app/main.py) | Liveness, dependency readiness, Prometheus text. |
| Auth | `POST /api/auth/register`; `POST /api/auth/login`; `POST /api/auth/api-keys`; `GET /api/auth/me` | [`auth.py`](../../../backend/app/routes/auth.py) | Token/API-key identity paths. |
| Chat | `POST /api/chat`; `POST /api/chat/stream`; `POST /api/chat/approve/{tool_call_id}`; `GET /api/chat/history/{conversation_id}` | [`chat.py`](../../../backend/app/routes/chat.py), [`stream.py`](../../../backend/app/routes/stream.py) | Sync, SSE, approval, history. |
| Conversations | `GET, POST /api/conversations`; `GET, DELETE /api/conversations/{conversation_id}` | [`conversations.py`](../../../backend/app/routes/conversations.py) | Owner-scoped lifecycle. |
| Runs | `GET /api/runs`; `GET /api/runs/compare`; `GET /api/runs/{run_id}`; `GET /api/runs/{run_id}/events`; `GET /api/runs/{run_id}/children`; `POST /api/runs/{run_id}/fork` | [`runs.py`](../../../backend/app/routes/runs.py) | Stored-only read/compare/fork paths. |
| Documents/RAG | `POST /api/documents/upload`; `POST /api/documents/query`; `GET /api/documents`; `DELETE /api/documents/{document_id}` | [`documents.py`](../../../backend/app/routes/documents.py) | Query invokes grounded document workflow. |
| Evaluations | `POST /api/evals/runs`; `GET /api/evals`; `GET /api/evals/compare`; `GET /api/evals/{evaluation_id}` | [`evaluations.py`](../../../backend/app/routes/evaluations.py) | Recorded-run deterministic evaluation. |
| Memory | `GET /api/memory/facts`; `GET /api/memory/export`; `DELETE /api/memory/facts`; `GET /api/memory/tiers`; `GET /api/memory/context` | [`memory.py`](../../../backend/app/routes/memory.py) | Router exists only when encrypted memory is enabled. Durable checkpoint/fork lives under the Runs API. |
| MCP | `GET /api/mcp/profiles`; `POST, GET /api/mcp/servers`; `GET, PATCH, DELETE /api/mcp/servers/{server_id}`; `POST .../{server_id}/discover`; `GET .../{server_id}/tools`; `PATCH .../{server_id}/tools/{tool_name}` | [`mcp.py`](../../../backend/app/routes/mcp.py) | `/api/mcp/request` and `/api/mcp/tools` are `410 Gone` compatibility endpoints. |
| Tasks | `POST /api/tasks/submit`; `GET /api/tasks`; `GET /api/tasks/{task_id}` | [`tasks.py`](../../../backend/app/routes/tasks.py) | Background-task surface. |
| Artifacts | `GET /api/artifacts`; `GET /api/artifacts/{artifact_id}`; `GET .../{artifact_id}/render`; `PUT, DELETE .../{artifact_id}` | [`artifacts.py`](../../../backend/app/routes/artifacts.py) | Authenticated artifact operations. |
| Skills | `GET, POST /api/skills`; `GET, DELETE /api/skills/{name}`; `POST /api/skills/search`; `POST /api/skills/import` | [`skills.py`](../../../backend/app/routes/skills.py) | Mutating endpoints include stronger dependencies where declared. |
| Admin | `GET /api/admin/health`; audit list/stats/search; metrics; breaker list/reset; settings get/update | [`admin.py`](../../../backend/app/routes/admin.py) | Router requires admin. |
| Security demos | compliance policies, PII scan, guardrail, permission, demo report, red-team, fuzz, evaluate, evaluators | [`compliance.py`](../../../backend/app/routes/compliance.py), [`security_demo.py`](../../../backend/app/routes/security_demo.py), [`red_team.py`](../../../backend/app/routes/red_team.py) | Red-team routes require admin; legacy A/B and harness routes return `410`. |
| Logs | `GET /api/logs/stream`; `GET /api/logs/recent` | [`log_stream.py`](../../../backend/app/routes/log_stream.py) | Safe owner-scoped operational stream. |
| Images | `GET /api/images/{filename}` | [`images.py`](../../../backend/app/routes/images.py) | Filename/path controls are in the route. |
| Research | `POST /v1/research` | [`research/api.py`](../../../backend/app/research/api.py) | Separate research workflow. |
| Legacy multi-agent | `POST /api/chat/multi-agent` | [`multi_agent.py`](../../../backend/app/routes/multi_agent.py) | Do not infer a dynamic production swarm; see current evidence. |

## How to refresh

Inspect `APIRouter(prefix=...)`, route decorators, dependencies, conditional `include_router` calls, and app-level routes. Compare the running `/openapi.json` only in a safe local environment and record its revision/configuration. This page intentionally omits request bodies and response fields to avoid becoming a second schema source.
