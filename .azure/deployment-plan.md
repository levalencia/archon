# Azure Deployment Plan

> **Status:** Deferred by user — local-only target selected

Updated: 2026-08-27

## Decision

Luis explicitly chose not to deploy Archon to Azure or any public environment during this evidence cycle. No Azure infrastructure, resource group, registry, database, secret store, DNS, or billable service was created or modified.

The verified target is the production-like local Docker Compose stack documented in:

- `docker-compose.local.yml`
- `docs/adr/0001-local-production-like-deployment.md`
- `docs/IMPLEMENTATION-EVIDENCE.md`

## What was not authorized

- quota or capacity reservation;
- Bicep/Terraform generation as a claimed deployable target;
- `azd provision` or `azd deploy`;
- public ingress, DNS, TLS or WAF changes;
- managed PostgreSQL/Redis/OTEL services;
- subscription or resource-group changes;
- cloud costs.

## Evidence status

`Deployed` remains **No** in the canonical evidence matrix. Local Docker build, smoke, DR and benchmark evidence must not be represented as Azure or production deployment.

## Reopen criteria

Reopen planning only after explicit user authorization and agreement on:

1. subscription and region;
2. budget and teardown policy;
3. public/private ingress, DNS and TLS;
4. managed PostgreSQL, Redis and secret storage;
5. external model/search/embedding providers;
6. backup/PITR and recovery objectives;
7. observability, SLOs and alerts;
8. image registry/scanning/signing;
9. migration, rollback and incident ownership.

Until then, the authoritative operational path is local-only.
