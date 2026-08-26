#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  printf 'Usage: %s COMPOSE_PROJECT ENV_FILE INPUT_DUMP\n' "${0##*/}" >&2
  exit 64
}

[[ $# -eq 3 ]] || usage
COMPOSE_PROJECT=$1
ENV_FILE=$2
INPUT_DUMP=$3
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
COMPOSE_FILE="$ROOT/docker-compose.local.yml"
CHECKSUM_FILE="${INPUT_DUMP}.sha256"

[[ -n "$COMPOSE_PROJECT" && -f "$ENV_FILE" && -r "$INPUT_DUMP" && -r "$CHECKSUM_FILE" ]] || usage
python3 - "$ENV_FILE" <<'PY'
import os
import stat
import sys
if stat.S_IMODE(os.stat(sys.argv[1]).st_mode) & 0o077:
    raise SystemExit("environment file must not be group/world-readable")
PY

expected=$(python3 - "$CHECKSUM_FILE" <<'PY'
import re
import sys
line = open(sys.argv[1], encoding="utf-8").readline()
value = line.split(maxsplit=1)[0] if line else ""
if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
    raise SystemExit("invalid SHA256 sidecar")
print(value.lower())
PY
)
actual=$(python3 - "$INPUT_DUMP" <<'PY'
import hashlib
import sys
h = hashlib.sha256()
with open(sys.argv[1], "rb") as stream:
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        h.update(block)
print(h.hexdigest())
PY
)
if [[ "$actual" != "$expected" ]]; then
  printf 'Backup SHA256 verification failed\n' >&2
  exit 65
fi

compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT")
user_table_count=$("${compose[@]}" exec -T postgres psql -U archon -d archon -Atqc \
  "SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'")
if [[ ! "$user_table_count" =~ ^[0-9]+$ ]]; then
  printf 'Unable to inspect target database\n' >&2
  exit 70
fi
if (( user_table_count > 0 )) && [[ "${ALLOW_REPLACE:-0}" != "1" ]]; then
  printf 'Refusing to replace a target containing Archon user tables; set ALLOW_REPLACE=1 explicitly\n' >&2
  exit 73
fi

"${compose[@]}" exec -T postgres pg_restore -U archon -d archon \
  --clean --if-exists --no-owner --no-acl --exit-on-error <"$INPUT_DUMP"
printf 'Restore completed and checksum verified.\n'
