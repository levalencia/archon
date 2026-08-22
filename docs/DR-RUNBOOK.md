# Archon — Disaster Recovery Runbook

## 1. Service Health Checks

```bash
# Backend
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz

# PostgreSQL
docker exec archon-postgres pg_isready -U archon

# Redis
docker exec archon-redis redis-cli ping

# Jaeger
curl http://localhost:16686/api/services
```

## 2. Common Failures & Recovery

### Backend won't start
```bash
# Check logs
docker compose logs backend --tail 50

# Common causes:
# 1. PostgreSQL not ready → wait for health check
# 2. Missing .env → copy from .env.example
# 3. Port 8000 in use → kill existing process
lsof -i :8000 | grep LISTEN
```

### PostgreSQL connection refused
```bash
# Restart PostgreSQL
docker compose restart postgres

# Check disk space (full disk = PG crash)
df -h

# Restore from backup
docker exec archon-postgres pg_restore -U archon -d archon /backups/latest.dump
```

### Redis connection refused
```bash
# Redis is optional — backend falls back to in-memory
# Restart if needed
docker compose restart redis
```

### Ollama not responding
```bash
# Check Ollama process
ollama list
curl http://localhost:11434/api/tags

# Restart
ollama serve &

# Backend switches to MockLLM if Ollama is down
# Change provider in .env: ARCHON_LLM_PROVIDER=mock
```

### Circuit breaker stuck OPEN
```bash
# Reset via API
curl -X POST http://localhost:8000/api/admin/circuit-breakers/{name}/reset

# Or restart backend (resets all circuit breakers)
docker compose restart backend
```

## 3. Backup Procedures

### Database backup
```bash
# Manual backup
docker exec archon-postgres pg_dump -U archon archon > backup_$(date +%Y%m%d).sql

# Scheduled (add to crontab)
0 2 * * * docker exec archon-postgres pg_dump -U archon archon > /backups/archon_$(date +\%Y\%m\%d).sql
```

### Redis backup
```bash
docker exec archon-redis redis-cli BGSAVE
docker cp archon-redis:/data/dump.rdb ./backups/redis_$(date +%Y%m%d).rdb
```

## 4. Scaling

### Horizontal (more backend replicas)
```bash
# Docker Compose
docker compose up --scale backend=3

# Kubernetes
kubectl scale deployment archon-backend --replicas=5
```

### Vertical (more resources)
```yaml
# In docker-compose.prod.yml or K8s
resources:
  limits:
    cpu: 2000m
    memory: 1Gi
```

## 5. Rollback

```bash
# Docker: roll back to previous image
docker compose pull backend
docker compose up -d backend

# Kubernetes
kubectl rollout undo deployment/archon-backend

# Database migration rollback (if using Alembic)
alembic downgrade -1
```

## 6. Monitoring Alerts

| Metric | Threshold | Action |
|---|---|---|
| `/healthz` fails | 3 consecutive | Restart backend pod |
| Response time > 10s | 5 min sustained | Scale up replicas |
| Circuit breaker OPEN | Any | Check upstream LLM provider |
| Disk usage > 80% | Alert | Clean old logs, rotate backups |
| Token cost > $10/day | Alert | Check for runaway conversations |
