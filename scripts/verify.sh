#!/usr/bin/env bash
set -euo pipefail
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:${PATH:-}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="archon-backend:verify"
CONTAINER="${ARCHON_VERIFY_CONTAINER:-archon-backend-verify-$$}"
CONTAINER_ID=""
PORT="${ARCHON_VERIFY_PORT:-18000}"
PLATFORM="${ARCHON_VERIFY_PLATFORM:-linux/amd64}"
VERIFY_TMPDIR="$(mktemp -d "${TMPDIR:-/tmp}/archon-verify.XXXXXX")"
BENCHMARK_REPORT="$VERIFY_TMPDIR/portfolio-benchmark.json"

ACCEPTANCE_SCRIPTS=(
  scripts/acceptance_support.py
  scripts/embedding_smoke.py
  scripts/multimodal_smoke.py
  scripts/portfolio_benchmark.py
  scripts/provider_acceptance.py
  ../scripts/sandbox_smoke.py
)
SHELL_SCRIPTS=(
  "$ROOT/scripts/verify.sh"
  "$ROOT/scripts/build-sandbox.sh"
  "$ROOT/scripts/local-deploy-smoke.sh"
  "$ROOT/scripts/local-dr-smoke.sh"
)

cleanup() {
  local status=$?
  local cleanup_failed=0
  trap - EXIT
  set +e
  if [[ -n "$CONTAINER_ID" ]] && command -v docker >/dev/null 2>&1; then
    docker rm -f "$CONTAINER_ID" >/dev/null 2>&1 || cleanup_failed=1
  fi
  rm -rf "$VERIFY_TMPDIR" || cleanup_failed=1
  if [[ "$status" -eq 0 && "$cleanup_failed" -ne 0 ]]; then
    printf 'Verification cleanup failed.\n' >&2
    status=1
  fi
  exit "$status"
}
trap cleanup EXIT

assert_clean_tree() {
  local workspace_status
  workspace_status="$(git -C "$ROOT" status --porcelain=v1 --untracked-files=all)"
  if [[ -n "$workspace_status" ]]; then
    printf 'Verification requires a clean worktree; found:\n%s\n' "$workspace_status" >&2
    return 1
  fi
}

printf '\n== Clean workspace preflight ==\n'
assert_clean_tree

printf '\n== Shell script syntax ==\n'
bash -n "${SHELL_SCRIPTS[@]}"

printf '\n== Acceptance script lint ==\n'
(
  cd "$ROOT/backend"
  uv run --extra dev ruff check "${ACCEPTANCE_SCRIPTS[@]}"
  uv run --extra dev ruff format --check "${ACCEPTANCE_SCRIPTS[@]}"
)

printf '\n== Acceptance script tests ==\n'
(
  cd "$ROOT/backend"
  uv run --extra dev pytest -q tests/unit/test_provider_acceptance_scripts.py
)

printf '\n== Capability acceptance manifest ==\n'
(
  cd "$ROOT/backend"
  uv run python -m app.capabilities.acceptance \
    ../docs/implementation/CAPABILITY-ACCEPTANCE.yaml
)

printf '\n== Backend lint ==\n'
(
  cd "$ROOT/backend"
  uv run --extra dev ruff check app tests
  uv run --extra dev ruff format --check app tests
  uv run --extra dev bandit -r app -ll
)

printf '\n== Backend tests ==\n'
(
  cd "$ROOT/backend"
  uv run --extra dev pytest -q --cov=app --cov-report=term-missing --cov-fail-under=50
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

printf '\n== Docker sandbox containment smoke ==\n'
SANDBOX_IMAGE_ID="$("$ROOT/scripts/build-sandbox.sh")"
(
  cd "$ROOT/backend"
  ARCHON_SANDBOX_IMAGE="$SANDBOX_IMAGE_ID" uv run python ../scripts/sandbox_smoke.py
)
unset SANDBOX_IMAGE_ID

printf '\n== Backend container smoke test ==\n'
if docker container inspect "$CONTAINER" >/dev/null 2>&1; then
  printf 'Refusing to remove pre-existing container: %s\n' "$CONTAINER" >&2
  exit 1
fi
docker build --platform "$PLATFORM" -t "$IMAGE" "$ROOT"
memory_master_key="$(
  cd "$ROOT/backend"
  uv run python -c 'import secrets; from app.memory.keys import decode_memory_master_key; key = secrets.token_urlsafe(32); decode_memory_master_key(key); print(key, end="")'
)"
CONTAINER_ID="$(ARCHON_ENCRYPTION_MASTER_KEY="$memory_master_key" docker run -d \
  --platform "$PLATFORM" \
  --name "$CONTAINER" -p "$PORT:8000" \
  -e ARCHON_DATABASE_URL="sqlite+aiosqlite:////tmp/archon-verify.db" \
  -e ARCHON_MEMORY_ENCRYPTION_ENABLED=true \
  -e ARCHON_ENCRYPTION_MASTER_KEY \
  "$IMAGE")"
unset memory_master_key

ready=0
for _ in {1..30}; do
  if curl --fail --silent "http://localhost:${PORT}/healthz" >/dev/null; then
    ready=1
    break
  fi
  sleep 1
done

if [[ "$ready" -ne 1 ]]; then
  docker logs "$CONTAINER_ID"
  echo "Backend container did not become healthy" >&2
  exit 1
fi

printf '\n== Final portfolio benchmark preflight ==\n'
(
  cd "$ROOT/backend"
  uv run python scripts/portfolio_benchmark.py --output "$BENCHMARK_REPORT" --iterations 1
)

printf '\n== Clean workspace verification ==\n'
assert_clean_tree

printf '\nAll Archon acceptance checks passed.\n'
