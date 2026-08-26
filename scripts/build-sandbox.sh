#!/usr/bin/env bash
set -euo pipefail
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:${PATH:-}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${ARCHON_SANDBOX_IMAGE:-archon-sandbox:local}"
PLATFORM="${ARCHON_VERIFY_PLATFORM:-linux/amd64}"
docker build --platform "$PLATFORM" -f "$ROOT/backend/Dockerfile.sandbox" -t "$IMAGE" "$ROOT/backend"
printf 'Built %s for %s\n' "$IMAGE" "$PLATFORM"
