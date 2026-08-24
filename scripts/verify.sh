#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="archon-backend:verify"
CONTAINER="archon-backend-verify"
PORT="${ARCHON_VERIFY_PORT:-18000}"

cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

printf '\n== Backend lint ==\n'
(
  cd "$ROOT/backend"
  uv run ruff check app tests
  uv run ruff format --check app tests
  uv run bandit -r app -ll
)

printf '\n== Backend tests ==\n'
(
  cd "$ROOT/backend"
  uv run pytest -q --cov=app --cov-report=term-missing --cov-fail-under=50
)

printf '\n== Frontend static checks ==\n'
(
  cd "$ROOT/frontend"
  npm run check
)

printf '\n== Frontend tests ==\n'
(
  cd "$ROOT/frontend"
  npm test -- --run
)

printf '\n== Frontend production build ==\n'
(
  cd "$ROOT/frontend"
  npm run build
)

printf '\n== Frontend browser tests ==\n'
(
  cd "$ROOT/frontend"
  npx playwright test
)

printf '\n== Backend container smoke test ==\n'
cleanup
docker build -t "$IMAGE" "$ROOT"
docker run -d --name "$CONTAINER" -p "$PORT:8000" \
  -e ARCHON_DATABASE_URL="sqlite+aiosqlite:////tmp/archon-verify.db" \
  "$IMAGE" >/dev/null

ready=0
for _ in {1..30}; do
  if curl --fail --silent "http://localhost:${PORT}/healthz" >/dev/null; then
    ready=1
    break
  fi
  sleep 1
done

if [[ "$ready" -ne 1 ]]; then
  docker logs "$CONTAINER"
  echo "Backend container did not become healthy" >&2
  exit 1
fi

printf '\nAll Archon acceptance checks passed.\n'
