# Archon Local Disaster-Recovery Runbook

## Scope

This runbook covers the verified `docker-compose.local.yml` target only. PostgreSQL is authoritative for users, conversations, runs/events, documents/chunks, approvals, memory, evaluations, and MCP inventory. Redis is required for live rate limiting but is not part of the durable evidence backup.

It does not claim cloud, multi-region, managed-database, point-in-time-recovery, or production RTO/RPO evidence.

## Prerequisites

- Docker Desktop and Compose v2
- `docker-compose.local.yml`
- the exact mode-`0600` env file used by the stack
- the Compose project name
- enough protected disk space for a PostgreSQL custom-format dump

Never print, commit, or copy the env file into the repository.

## Health and readiness

The verified stack publishes only the gateway on loopback:

```bash
curl --fail http://127.0.0.1:${ARCHON_LOCAL_PORT:-8080}/healthz
curl --fail http://127.0.0.1:${ARCHON_LOCAL_PORT:-8080}/readyz
curl --fail http://127.0.0.1:${ARCHON_LOCAL_PORT:-8080}/metrics
```

`/readyz` checks PostgreSQL, Redis rate-limit storage, embedding capability, and active OTEL configuration. Redis failure is not silently replaced by an in-memory limiter in the verified target.

## Create a backup

```bash
./scripts/local-backup.sh \
  <compose-project> \
  </absolute/path/to/mode-0600.env> \
  </protected/path/archon.dump>
```

The script:

1. rejects a missing or world-readable env file;
2. refuses to overwrite the dump or sidecars;
3. uses `pg_dump -Fc --no-owner --no-acl` inside the private PostgreSQL service;
4. writes through a temporary file and moves atomically;
5. sets mode `0600`;
6. writes `<dump>.sha256` and `<dump>.metadata.json`;
7. records UTC snapshot time and Alembic revision without credentials.

Verify artifacts exist:

```bash
stat -f '%Sp %N' /protected/path/archon.dump*
```

Do not use the old plaintext `docker exec ... pg_dump > backup.sql` instructions from historical docs.

## Restore into a clean target

Start only destination dependencies in a fresh Compose project/volume:

```bash
ARCHON_LOCAL_PORT=18081 docker compose \
  --env-file /absolute/path/to/mode-0600.env \
  -f docker-compose.local.yml \
  -p archon-restore \
  up -d --wait postgres redis otel-collector
```

Restore:

```bash
./scripts/local-restore.sh \
  archon-restore \
  /absolute/path/to/mode-0600.env \
  /protected/path/archon.dump
```

The restore script verifies SHA-256 and refuses a target containing Archon user tables. `ALLOW_REPLACE=1` is the only explicit destructive override and should not be used for the clean-restore drill.

Start the application after restore:

```bash
ARCHON_LOCAL_PORT=18081 docker compose \
  --env-file /absolute/path/to/mode-0600.env \
  -f docker-compose.local.yml \
  -p archon-restore \
  up --build -d --wait
```

Confirm readiness and revision:

```bash
curl --fail http://127.0.0.1:18081/readyz

docker compose \
  --env-file /absolute/path/to/mode-0600.env \
  -f docker-compose.local.yml \
  -p archon-restore \
  exec -T postgres \
  psql -U archon -d archon -Atqc 'SELECT version_num FROM alembic_version'
```

Expected revision for the recorded S7 evidence: `20260826_08`.

## Automated clean-restore proof

```bash
./scripts/local-dr-smoke.sh /tmp/archon-dr-report.json
```

The smoke:

- creates secure temporary credentials and two isolated Compose projects;
- creates a user, conversation, durable run/events, document/chunk, and terminal approval;
- records exact IDs, counts, content hashes and approval argument hash;
- performs a checksummed backup;
- destroys the source project and volumes;
- restores into a fresh PostgreSQL target before starting the application;
- authenticates with the restored account and verifies evidence through APIs and SQL;
- measures backup duration and restore-to-ready RTO;
- reports record-level RPO at the snapshot boundary;
- removes projects, volumes, dump, sidecars and env file by default.

`KEEP=1` is a debugging opt-in and retains sensitive temporary material. Use it only on a controlled machine and clean it immediately.

## Recorded local evidence

See [`evidence/local-dr-report.json`](evidence/local-dr-report.json).

| Measurement | Observed local result |
|---|---:|
| Backup duration | 0.343 s |
| Restore-to-ready RTO | 21.586 s |
| RPO at snapshot boundary | 0 changed records |
| Restored run events | 5 |
| Documents / chunks / terminal approvals | 1 / 1 / 1 |
| Schema revision | `20260826_08` |

These values describe one development Mac run with cached images. They are not production SLOs.

## Failure handling

### Checksum mismatch

Do not restore. Quarantine the dump and sidecars; locate a matching backup set.

### Non-empty target refusal

Create a new Compose project/volume. Do not set `ALLOW_REPLACE=1` unless destruction is explicitly intended and separately approved.

### Backend fails after restore

```bash
docker compose --env-file "$ENV_FILE" -f docker-compose.local.yml -p "$PROJECT" logs backend
```

Check Alembic revision, encryption key continuity, PostgreSQL readiness, Redis readiness, and image architecture. Existing encrypted memory requires the same master key.

### Cleanup

```bash
docker compose \
  --env-file /absolute/path/to/mode-0600.env \
  -f docker-compose.local.yml \
  -p archon-restore \
  down --volumes --remove-orphans
```

## Operational gaps

- No scheduled backups or retention policy are configured.
- No remote encrypted backup store was verified.
- No PITR/WAL archive was tested.
- No cloud failover or multi-region exercise was performed.
- Key rotation and cross-key restore remain manual procedures.
