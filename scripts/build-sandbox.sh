#!/usr/bin/env bash
set -euo pipefail
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:${PATH:-}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${ARCHON_SANDBOX_IMAGE:-archon-sandbox:local}"
PLATFORM="${ARCHON_VERIFY_PLATFORM:-linux/amd64}"

docker build --platform "$PLATFORM" -f "$ROOT/backend/Dockerfile.sandbox" -t "$IMAGE" "$ROOT/backend" >&2
IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$IMAGE")"
if [[ ! "$IMAGE_ID" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  printf 'Built sandbox did not resolve to an immutable image ID\n' >&2
  exit 1
fi
printf 'Built %s for %s (%s)\n' "$IMAGE" "$PLATFORM" "$IMAGE_ID" >&2
# stdout is intentionally machine-readable so verification passes the exact immutable ID.
printf '%s\n' "$IMAGE_ID"
