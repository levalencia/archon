# ADR 0001: Verify one production-like local deployment target

- **Status:** Accepted
- **Date:** 2026-08-27
- **Decision owners:** Archon maintainers

## Context

Archon contained several packaging artifacts—development processes, a stale production Compose file, Helm/Kubernetes examples—but none constituted verified deployment evidence. Some historical files also implied pgvector, optional Redis fallback, or cloud readiness that the live product did not prove.

The roadmap requested one explicit target rather than multiple unverified options. A public Azure deployment was considered, but Luis explicitly chose local-only verification and no cloud resource creation.

## Decision

Adopt `docker-compose.local.yml` as the sole verified target for this portfolio phase.

The target contains:

- loopback-only unprivileged Nginx gateway;
- SvelteKit adapter-node frontend;
- FastAPI backend with Alembic-before-Uvicorn entrypoint;
- PostgreSQL 16 and Redis 7 on internal networks only;
- OTEL collector with OTLP gRPC and local debug export;
- digest-pinned base/service images;
- non-root app processes and read-only filesystems where supported;
- required environment-injected credentials with no defaults;
- explicit mock model/embedding providers and disabled optional execution.

The backend defaults to `linux/amd64` for this target because the native ARM image reproducibly exited with `SIGILL` while importing `cryptography` on the verified Mac. This is an explicit compatibility boundary, not a claim that ARM support is fixed.

## Why this target

- It exercises real PostgreSQL, Redis, OTEL, migrations, gateway routing, frontend runtime and backend runtime together.
- It can be reproduced without cloud credentials or cost.
- It supports destructive DR drills with isolated project names and volumes.
- It keeps the evidence honest: local verification is not public deployment.

## Alternatives considered

### Azure Container Apps

Deferred by user decision. No subscription/resource changes were authorized. Preparing multiple cloud templates without deployment evidence would increase maintenance and false-confidence risk.

### Kubernetes/Helm

Existing artifacts were not selected. Verifying cluster operations, secrets, storage classes, ingress, autoscaling, rollback and observability would exceed the local-only scope.

### Legacy `docker-compose.prod.yml`

Rejected as the verified target because it contained stale assumptions, mutable/hardcoded configuration, and unproven pgvector/operational claims.

## Consequences

### Positive

- One runnable, tested path.
- Real dependencies and migration behavior are observable.
- Backup/restore and benchmark evidence is reproducible.
- No database, Redis, or OTEL host ports are exposed.

### Negative

- Local Docker and the host daemon remain trusted.
- The backend uses emulated amd64 on Apple Silicon.
- There is no public URL, managed secret store, cloud database, remote trace backend, autoscaling or production traffic evidence.
- Mock providers mean the target proves control-plane wiring, not external-model quality.

## Verification

- `./scripts/local-deploy-smoke.sh`
- `./scripts/local-dr-smoke.sh /tmp/archon-dr-report.json`
- `./scripts/verify.sh`
- [`../evidence/local-dr-report.json`](../evidence/local-dr-report.json)
- [`../evidence/local-portfolio-benchmark.json`](../evidence/local-portfolio-benchmark.json)

## Revisit when

Revisit this ADR only after explicit authorization for a public target and agreement on budget, subscription, region, managed database, secrets, DNS/TLS, rollback, observability and teardown policy.
