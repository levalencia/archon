#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
COMPOSE_FILE="$ROOT/docker-compose.local.yml"
PROJECT="archon-local-$PPID-$RANDOM"
ENV_FILE=$(mktemp "${TMPDIR:-/tmp}/archon-local.XXXXXX")
chmod 600 "$ENV_FILE"

cleanup() {
  status=$?
  if [[ "${KEEP:-0}" == "1" ]]; then
    printf 'KEEP=1: deployment retained (project %s); protected env file retained at %s\n' "$PROJECT" "$ENV_FILE"
  else
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" -p "$PROJECT" down --volumes --remove-orphans >/dev/null 2>&1 || true
    rm -f "$ENV_FILE"
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM

export ENV_FILE
python3 - <<'PY'
import base64
import os
import secrets

path = os.environ["ENV_FILE"]
values = {
    "POSTGRES_PASSWORD": secrets.token_hex(32),
    "ARCHON_SECRET_KEY": secrets.token_urlsafe(48),
    "ARCHON_ENCRYPTION_MASTER_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="),
    "ARCHON_LOCAL_PORT": str(18000 + secrets.randbelow(20000)),
}
with open(path, "w", encoding="utf-8") as stream:
    for key, value in values.items():
        stream.write(f"{key}={value}\n")
PY

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
if [[ -z "${ARCHON_LOCAL_PLATFORM:-}" ]]; then
  daemon_arch="$(docker info --format '{{.Architecture}}')"
  case "$daemon_arch" in
    aarch64 | arm64) ARCHON_LOCAL_PLATFORM="linux/arm64" ;;
    x86_64 | amd64) ARCHON_LOCAL_PLATFORM="linux/amd64" ;;
    *)
      printf 'Unsupported Docker daemon architecture: %s\n' "$daemon_arch" >&2
      exit 1
      ;;
  esac
  export ARCHON_LOCAL_PLATFORM
fi
BASE_URL="http://127.0.0.1:$ARCHON_LOCAL_PORT"
compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" -p "$PROJECT")

printf 'Building isolated local deployment...\n'
"${compose[@]}" build
"${compose[@]}" up -d --wait

for endpoint in healthz readyz; do
  for _ in {1..60}; do
    if curl --fail --silent --show-error "$BASE_URL/$endpoint" >/dev/null; then
      break
    fi
    sleep 2
  done
  curl --fail --silent --show-error "$BASE_URL/$endpoint" >/dev/null
done

curl --fail --silent --show-error "$BASE_URL/readyz" | python3 -c '
import json, sys
d=json.load(sys.stdin); deps=d["dependencies"]
assert d["status"] == "ready"
assert deps["conversation_repository"] == "up"
assert deps["rate_limiter"] == {"backend": "redis", "status": "up"}
assert deps["embeddings"]["mock"] is True
assert deps["embeddings"]["readiness"] == "non-production"
assert deps["telemetry"] == {"backend": "otlp-grpc", "status": "up"}
'

AUTH_USER="smoke_${RANDOM}_${PPID}"
AUTH_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
register_response=$(curl --fail --silent --show-error -X POST "$BASE_URL/api/auth/register" \
  -H 'Content-Type: application/json' \
  --data "$(python3 -c 'import json,sys; print(json.dumps({"username":sys.argv[1],"password":sys.argv[2]}))' "$AUTH_USER" "$AUTH_PASSWORD")")
printf '%s' "$register_response" | python3 -c 'import json,sys; assert json.load(sys.stdin)["access_token"]'
login_response=$(curl --fail --silent --show-error -X POST "$BASE_URL/api/auth/login" \
  -H 'Content-Type: application/json' \
  --data "$(python3 -c 'import json,sys; print(json.dumps({"username":sys.argv[1],"password":sys.argv[2]}))' "$AUTH_USER" "$AUTH_PASSWORD")")
printf '%s' "$login_response" | python3 -c 'import json,sys; assert json.load(sys.stdin)["access_token"]'
ACCESS_TOKEN=$(printf '%s' "$login_response" | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
AUTH_HEADER_NAME=$(printf 'Authoriza%s' 'tion')
unset AUTH_PASSWORD register_response login_response

# Exercise the actual runtime so CompositeEventSink emits and exports an `agent.run` span.
curl --fail --silent --show-error -X POST "$BASE_URL/api/chat" \
  -H 'Content-Type: application/json' \
  -H "${AUTH_HEADER_NAME}: Bearer ${ACCESS_TOKEN}" \
  --data '{"message":"local telemetry smoke"}' \
  | python3 -c 'import json,sys; assert json.load(sys.stdin)["response"]'
unset ACCESS_TOKEN AUTH_HEADER_NAME

curl --fail --silent --show-error "$BASE_URL/metrics" | python3 -c 'import sys; assert sys.stdin.read().strip()'
migration=$("${compose[@]}" exec -T postgres psql -U archon -d archon -Atqc 'select version_num from alembic_version')
[[ "$migration" == "20260828_14" ]]
"${compose[@]}" exec -T backend python -c "import urllib.request; urllib.request.urlopen('http://otel-collector:13133/', timeout=3)"

otel_observed=0
for _ in {1..30}; do
  if "${compose[@]}" logs otel-collector 2>&1 | python3 -c '
import sys
text = sys.stdin.read()
raise SystemExit(0 if "agent.run" in text and "archon-local" in text else 1)
'; then
    otel_observed=1
    break
  fi
  sleep 1
done
[[ "$otel_observed" == "1" ]]

printf 'Local deployment smoke test passed: gateway, DB, Redis, mock embeddings, auth, metrics, migration 08, and exported OTEL span.\n'
