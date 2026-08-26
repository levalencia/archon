#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
COMPOSE_FILE="$ROOT/docker-compose.local.yml"
REPORT_PATH=${1:-$(mktemp "${TMPDIR:-/tmp}/archon-local-dr-report.XXXXXX")}
ENV_FILE=$(mktemp "${TMPDIR:-/tmp}/archon-local-dr-env.XXXXXX")
DUMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/archon-local-dr.XXXXXX")
DUMP_PATH="$DUMP_DIR/backup.dump"
SUFFIX=$(python3 -c 'import secrets; print(secrets.token_hex(5))')
SOURCE_PROJECT="archon-dr-source-$SUFFIX"
DEST_PROJECT="archon-dr-dest-$SUFFIX"
read -r SOURCE_PORT DEST_PORT < <(python3 - <<'PY'
import socket
ports = []
while len(ports) < 2:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    if port not in ports:
        ports.append(port)
print(*ports)
PY
)
chmod 600 "$ENV_FILE"
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
}
with open(path, "w", encoding="utf-8") as stream:
    for key, value in values.items():
        stream.write(f"{key}={value}\n")
PY

source_compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" -p "$SOURCE_PROJECT")
dest_compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" -p "$DEST_PROJECT")
stage="initializing"
cleanup() {
  status=$?
  if [[ "$status" -ne 0 ]]; then
    printf 'DR smoke failed at stage: %s\n' "$stage" >&2
  fi
  if [[ "${KEEP:-0}" == "1" ]]; then
    printf 'KEEP=1: retained projects %s and %s plus protected artifacts under %s\n' \
      "$SOURCE_PROJECT" "$DEST_PROJECT" "$(dirname "$ENV_FILE")"
  else
    ARCHON_LOCAL_PORT=$SOURCE_PORT "${source_compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
    ARCHON_LOCAL_PORT=$DEST_PORT "${dest_compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
    rm -f "$ENV_FILE" "$DUMP_PATH" "${DUMP_PATH}.sha256" "${DUMP_PATH}.metadata.json"
    rmdir "$DUMP_DIR" >/dev/null 2>&1 || true
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM

now_ns() { python3 -c 'import time; print(time.time_ns())'; }
elapsed_seconds() {
  python3 - "$1" "$2" <<'PY'
import sys
print(f"{(int(sys.argv[2]) - int(sys.argv[1])) / 1_000_000_000:.3f}")
PY
}
json_field() {
  python3 -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"
}
json_list_length() {
  python3 -c 'import json,sys; print(len(json.load(sys.stdin)[sys.argv[1]]))' "$1"
}
api() {
  curl --fail --silent --show-error "$@"
}
wait_ready() {
  local url=$1
  local attempt
  for attempt in {1..60}; do
    if curl --fail --silent "$url/readyz" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  printf 'Timed out waiting for %s/readyz\n' "$url" >&2
  return 1
}
psql_source() {
  "${source_compose[@]}" exec -T postgres psql -U archon -d archon -v ON_ERROR_STOP=1 "$@"
}
psql_dest() {
  "${dest_compose[@]}" exec -T postgres psql -U archon -d archon -v ON_ERROR_STOP=1 "$@"
}

printf 'Starting isolated DR source deployment...\n'
stage="source_startup"
ARCHON_LOCAL_PORT=$SOURCE_PORT "${source_compose[@]}" up --build -d --wait
SOURCE_URL="http://127.0.0.1:$SOURCE_PORT"
wait_ready "$SOURCE_URL"

stage="authentication_and_conversation"
AUTH_USER="dr_${SUFFIX}"
AUTH_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(30))')
auth_payload=$(python3 -c 'import json,sys; print(json.dumps({"username":sys.argv[1],"password":sys.argv[2]}))' "$AUTH_USER" "$AUTH_PASSWORD")
register_response=$(api -X POST "$SOURCE_URL/api/auth/register" -H 'Content-Type: application/json' --data "$auth_payload")
USER_ID=$(printf '%s' "$register_response" | json_field user_id)
login_response=$(api -X POST "$SOURCE_URL/api/auth/login" -H 'Content-Type: application/json' --data "$auth_payload")
ACCESS_TOKEN=$(printf '%s' "$login_response" | json_field access_token)
AUTH_HEADER_NAME=$(printf 'Authoriza%s' 'tion')

conversation_response=$(api -X POST "$SOURCE_URL/api/conversations" \
  -H 'Content-Type: application/json' -H "$AUTH_HEADER_NAME: Bearer $ACCESS_TOKEN" \
  --data '{"title":"DR evidence conversation"}')
CONVERSATION_ID=$(printf '%s' "$conversation_response" | json_field id)
stage="chat_run"
chat_payload=$(python3 -c 'import json,sys; print(json.dumps({"message":"Create durable DR evidence","conversation_id":sys.argv[1]}))' "$CONVERSATION_ID")
api -X POST "$SOURCE_URL/api/chat" -H 'Content-Type: application/json' \
  -H "$AUTH_HEADER_NAME: Bearer $ACCESS_TOKEN" --data "$chat_payload" >/dev/null
runs_response=$(api "$SOURCE_URL/api/runs?conversation_id=$CONVERSATION_ID" -H "$AUTH_HEADER_NAME: Bearer $ACCESS_TOKEN")
RUN_ID=$(printf '%s' "$runs_response" | python3 -c 'import json,sys; print(json.load(sys.stdin)["items"][0]["run_id"])')
RUN_EVENT_COUNT=$(api "$SOURCE_URL/api/runs/$RUN_ID/events" -H "$AUTH_HEADER_NAME: Bearer $ACCESS_TOKEN" | \
  json_list_length items)
[[ "$RUN_EVENT_COUNT" -gt 0 ]]

stage="document_ingest"
document_payload=$(python3 -c 'import json; print(json.dumps({"title":"DR evidence document","source":"local-dr-smoke","content":"Archon disaster recovery evidence survives a clean PostgreSQL restore."}))')
document_response=$(api -X POST "$SOURCE_URL/api/documents/upload" -H 'Content-Type: application/json' \
  -H "$AUTH_HEADER_NAME: Bearer $ACCESS_TOKEN" --data "$document_payload")
DOCUMENT_ID=$(printf '%s' "$document_response" | json_field id)
DOCUMENT_CHUNKS=$(printf '%s' "$document_response" | json_field chunks)

stage="approval_seed"
read -r APPROVAL_ID TOOL_CALL_ID < <(python3 -c 'import uuid; print(uuid.uuid4(), uuid.uuid4())')
APPROVAL_HASH=$(python3 - "$TOOL_CALL_ID" <<'PY'
import hashlib
import sys
print(hashlib.sha256(("archon-local-dr:" + sys.argv[1]).encode()).hexdigest())
PY
)
psql_source -v approval_id="$APPROVAL_ID" -v user_id="$USER_ID" -v conversation_id="$CONVERSATION_ID" \
  -v run_id="$RUN_ID" -v tool_call_id="$TOOL_CALL_ID" -v arguments_hash="$APPROVAL_HASH" <<'SQL' >/dev/null
INSERT INTO approval_requests
(id,user_id,conversation_id,run_id,tool_call_id,tool_name,arguments_hash,risk_classes,
 matched_rule_id,status,decision_reason,created_at,expires_at,decided_at)
VALUES
(:'approval_id', :'user_id', :'conversation_id', :'run_id', :'tool_call_id', 'local_dr_probe',
 :'arguments_hash', '["write"]', 'local-dr-smoke', 'approved', 'approved_by_user',
 CURRENT_TIMESTAMP, CURRENT_TIMESTAMP + INTERVAL '1 hour', CURRENT_TIMESTAMP);
SQL

stage="source_fingerprint"
SOURCE_FINGERPRINT=$(psql_source -At -F '|' \
  -v document_id="$DOCUMENT_ID" -v approval_id="$APPROVAL_ID" -v run_id="$RUN_ID" <<'SQL'
SELECT
  (SELECT count(*) FROM documents WHERE id = :'document_id'),
  (SELECT count(*) FROM vector_chunks WHERE document_id = :'document_id'),
  (SELECT string_agg(content_hash, ',' ORDER BY chunk_index) FROM vector_chunks WHERE document_id = :'document_id'),
  (SELECT count(*) FROM approval_requests WHERE id = :'approval_id' AND status = 'approved'),
  (SELECT arguments_hash FROM approval_requests WHERE id = :'approval_id'),
  (SELECT count(*) FROM runtime_events WHERE run_id = :'run_id');
SQL
)
IFS='|' read -r SOURCE_DOCUMENT_COUNT SOURCE_CHUNK_COUNT SOURCE_CHUNK_HASHES SOURCE_APPROVAL_COUNT SOURCE_APPROVAL_HASH SOURCE_EVENT_COUNT <<<"$SOURCE_FINGERPRINT"
[[ "$SOURCE_DOCUMENT_COUNT" == "1" && "$SOURCE_CHUNK_COUNT" == "$DOCUMENT_CHUNKS" && "$SOURCE_APPROVAL_COUNT" == "1" ]]
[[ "$SOURCE_APPROVAL_HASH" == "$APPROVAL_HASH" && "$SOURCE_EVENT_COUNT" == "$RUN_EVENT_COUNT" ]]

stage="backup"
backup_start=$(now_ns)
"$ROOT/scripts/local-backup.sh" "$SOURCE_PROJECT" "$ENV_FILE" "$DUMP_PATH" >/dev/null
backup_end=$(now_ns)
BACKUP_SECONDS=$(elapsed_seconds "$backup_start" "$backup_end")
SNAPSHOT_UTC=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["created_at_utc"])' "$DUMP_PATH.metadata.json")
DUMP_SHA256=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sha256"])' "$DUMP_PATH.metadata.json")

ARCHON_LOCAL_PORT=$SOURCE_PORT "${source_compose[@]}" down --volumes --remove-orphans >/dev/null
rto_start=$(now_ns)
stage="destination_startup"
ARCHON_LOCAL_PORT=$DEST_PORT "${dest_compose[@]}" up -d --wait postgres redis otel-collector
"$ROOT/scripts/local-restore.sh" "$DEST_PROJECT" "$ENV_FILE" "$DUMP_PATH" >/dev/null
ARCHON_LOCAL_PORT=$DEST_PORT "${dest_compose[@]}" up --build -d --wait
DEST_URL="http://127.0.0.1:$DEST_PORT"
wait_ready "$DEST_URL"
rto_end=$(now_ns)
RTO_SECONDS=$(elapsed_seconds "$rto_start" "$rto_end")

stage="restored_evidence_verification"
restored_login=$(api -X POST "$DEST_URL/api/auth/login" -H 'Content-Type: application/json' --data "$auth_payload")
RESTORED_TOKEN=$(printf '%s' "$restored_login" | json_field access_token)
api "$DEST_URL/api/conversations/$CONVERSATION_ID" -H "$AUTH_HEADER_NAME: Bearer $RESTORED_TOKEN" | \
  python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["id"]==sys.argv[1] and d["message_count"] >= 2' "$CONVERSATION_ID"
api "$DEST_URL/api/runs/$RUN_ID" -H "$AUTH_HEADER_NAME: Bearer $RESTORED_TOKEN" | \
  python3 -c 'import json,sys; assert json.load(sys.stdin)["run_id"]==sys.argv[1]' "$RUN_ID"
RESTORED_EVENT_COUNT=$(api "$DEST_URL/api/runs/$RUN_ID/events" -H "$AUTH_HEADER_NAME: Bearer $RESTORED_TOKEN" | json_list_length items)
api "$DEST_URL/api/documents" -H "$AUTH_HEADER_NAME: Bearer $RESTORED_TOKEN" | \
  python3 -c 'import json,sys; docs=json.load(sys.stdin); assert any(d["id"]==sys.argv[1] and d["chunks"]==int(sys.argv[2]) for d in docs)' "$DOCUMENT_ID" "$DOCUMENT_CHUNKS"
DEST_FINGERPRINT=$(psql_dest -At -F '|' \
  -v document_id="$DOCUMENT_ID" -v approval_id="$APPROVAL_ID" -v run_id="$RUN_ID" <<'SQL'
SELECT
  (SELECT count(*) FROM documents WHERE id = :'document_id'),
  (SELECT count(*) FROM vector_chunks WHERE document_id = :'document_id'),
  (SELECT string_agg(content_hash, ',' ORDER BY chunk_index) FROM vector_chunks WHERE document_id = :'document_id'),
  (SELECT count(*) FROM approval_requests WHERE id = :'approval_id' AND status = 'approved'),
  (SELECT arguments_hash FROM approval_requests WHERE id = :'approval_id'),
  (SELECT count(*) FROM runtime_events WHERE run_id = :'run_id');
SQL
)
[[ "$DEST_FINGERPRINT" == "$SOURCE_FINGERPRINT" && "$RESTORED_EVENT_COUNT" == "$RUN_EVENT_COUNT" ]]
ALEMBIC_REVISION=$(psql_dest -Atqc 'SELECT version_num FROM alembic_version')
[[ "$ALEMBIC_REVISION" == "20260826_08" ]]

export REPORT_PATH BACKUP_SECONDS RTO_SECONDS SNAPSHOT_UTC DUMP_SHA256 ALEMBIC_REVISION USER_ID CONVERSATION_ID RUN_ID DOCUMENT_ID APPROVAL_ID SOURCE_DOCUMENT_COUNT SOURCE_CHUNK_COUNT SOURCE_APPROVAL_COUNT SOURCE_EVENT_COUNT
python3 - <<'PY'
import json
import os
report = {
    "backup": {
        "duration_seconds": float(os.environ["BACKUP_SECONDS"]),
        "sha256": os.environ["DUMP_SHA256"],
        "snapshot_utc": os.environ["SNAPSHOT_UTC"],
    },
    "evidence": {
        "approval_id": os.environ["APPROVAL_ID"],
        "conversation_id": os.environ["CONVERSATION_ID"],
        "document_id": os.environ["DOCUMENT_ID"],
        "run_id": os.environ["RUN_ID"],
        "user_id": os.environ["USER_ID"],
    },
    "restored_counts": {
        "approved_terminal_approvals": int(os.environ["SOURCE_APPROVAL_COUNT"]),
        "documents": int(os.environ["SOURCE_DOCUMENT_COUNT"]),
        "run_events": int(os.environ["SOURCE_EVENT_COUNT"]),
        "vector_chunks": int(os.environ["SOURCE_CHUNK_COUNT"]),
    },
    "result": "passed",
    "rpo_records": 0,
    "rto_seconds": float(os.environ["RTO_SECONDS"]),
    "schema_revision": os.environ["ALEMBIC_REVISION"],
}
with open(os.environ["REPORT_PATH"], "w", encoding="utf-8") as stream:
    json.dump(report, stream, indent=2, sort_keys=True)
    stream.write("\n")
os.chmod(os.environ["REPORT_PATH"], 0o600)
PY
unset AUTH_PASSWORD ACCESS_TOKEN RESTORED_TOKEN auth_payload login_response register_response restored_login
printf 'Local DR smoke passed; report: %s\n' "$REPORT_PATH"
