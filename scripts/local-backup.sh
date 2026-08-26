#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  printf 'Usage: %s COMPOSE_PROJECT ENV_FILE OUTPUT_DUMP\n' "${0##*/}" >&2
  exit 64
}

[[ $# -eq 3 ]] || usage
COMPOSE_PROJECT=$1
ENV_FILE=$2
OUTPUT_DUMP=$3
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
COMPOSE_FILE="$ROOT/docker-compose.local.yml"
CHECKSUM_FILE="${OUTPUT_DUMP}.sha256"
METADATA_FILE="${OUTPUT_DUMP}.metadata.json"

[[ -n "$COMPOSE_PROJECT" && -f "$ENV_FILE" && -f "$COMPOSE_FILE" ]] || usage
for path in "$OUTPUT_DUMP" "$CHECKSUM_FILE" "$METADATA_FILE"; do
  if [[ -e "$path" ]]; then
    printf 'Refusing to overwrite existing backup artifact: %s\n' "$path" >&2
    exit 73
  fi
done

python3 - "$ENV_FILE" <<'PY'
import os
import stat
import sys
path = sys.argv[1]
mode = stat.S_IMODE(os.stat(path).st_mode)
if mode & 0o077:
    raise SystemExit("environment file must not be group/world-readable")
PY

output_dir=$(dirname "$OUTPUT_DUMP")
mkdir -p "$output_dir"
tmp_dump=$(mktemp "$output_dir/.archon-backup.dump.XXXXXX")
tmp_checksum=$(mktemp "$output_dir/.archon-backup.sha256.XXXXXX")
tmp_metadata=$(mktemp "$output_dir/.archon-backup.metadata.XXXXXX")
cleanup() { rm -f "$tmp_dump" "$tmp_checksum" "$tmp_metadata"; }
trap cleanup EXIT INT TERM
chmod 600 "$tmp_dump" "$tmp_checksum" "$tmp_metadata"
compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT")

revision=$("${compose[@]}" exec -T postgres psql -U archon -d archon -Atqc \
  'SELECT version_num FROM alembic_version')
[[ -n "$revision" ]] || { printf 'Unable to read Alembic revision\n' >&2; exit 70; }
created_at=$(python3 -c 'from datetime import UTC,datetime; print(datetime.now(UTC).isoformat().replace("+00:00","Z"))')

"${compose[@]}" exec -T postgres pg_dump -U archon -d archon \
  -Fc --no-owner --no-acl >"$tmp_dump"
[[ -s "$tmp_dump" ]] || { printf 'Backup dump is empty\n' >&2; exit 70; }

sha256=$(python3 - "$tmp_dump" <<'PY'
import hashlib
import sys
h = hashlib.sha256()
with open(sys.argv[1], "rb") as stream:
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        h.update(block)
print(h.hexdigest())
PY
)
printf '%s  %s\n' "$sha256" "$(basename "$OUTPUT_DUMP")" >"$tmp_checksum"
python3 - "$tmp_metadata" "$created_at" "$revision" "$sha256" <<'PY'
import json
import sys
path, created_at, revision, digest = sys.argv[1:]
metadata = {
    "alembic_revision": revision,
    "created_at_utc": created_at,
    "database": "archon",
    "dump_format": "postgresql-custom",
    "format_version": 1,
    "sha256": digest,
}
with open(path, "w", encoding="utf-8") as stream:
    json.dump(metadata, stream, sort_keys=True, separators=(",", ":"))
    stream.write("\n")
PY

mv "$tmp_dump" "$OUTPUT_DUMP"
mv "$tmp_checksum" "$CHECKSUM_FILE"
mv "$tmp_metadata" "$METADATA_FILE"
chmod 600 "$OUTPUT_DUMP" "$CHECKSUM_FILE" "$METADATA_FILE"
trap - EXIT INT TERM
printf 'Backup created: %s\n' "$OUTPUT_DUMP"
