#!/usr/bin/env bash
# deploy-vm.sh – Idempotent parity-preserving deployment for Cogentrex Azure VM.
# Validates a 40-char SHA, clones/fetches a public repo, generates protected env
# via canonical tooling, runs pg_dump backup before update, docker compose update
# preserving volumes, health/ready/media/sandbox checks, and rolls back on failure.
#
# Usage: deploy-vm.sh <40-char-SHA> [--repo URL] [--branch BRANCH]
#
# Environment:
#   COGENTREX_APP_ROOT   – application root (default: /opt/cogentrex)
#   COGENTREX_REPO_URL   – public git repo URL
#   COGENTREX_PUBLIC_IP   – VM public IP for sslip.io hostname
#   COGENTREX_OPENAI_ENDPOINT – Managed Identity OpenAI endpoint
#   COGENTREX_OPENAI_MODEL    – Model deployment name
#   APPLICATIONINSIGHTS_CONNECTION_STRING – App Insights connection string
set -Eeuo pipefail
shopt -s inherit_errexit

# ─── Constants ──────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SCRIPT_DIR
readonly APP_ROOT="${COGENTREX_APP_ROOT:-/opt/cogentrex}"
readonly REPO_URL="${COGENTREX_REPO_URL:-https://github.com/levalencia/cogentrex.git}"
readonly STATE_DIR="${XDG_STATE_HOME:-$APP_ROOT/.state}"
readonly BACKUP_DIR="${APP_ROOT}/backups"
readonly DEPLOY_STATE="${STATE_DIR}/deploy.env"
readonly TMPDIR_PERSIST="${TMPDIR:-/var/tmp/cogentrex}"
readonly COMPOSE_PROJECT="cogentrex-azure"
readonly COMPOSE_ENV_FILE="${APP_ROOT}/.env.azure"
readonly COMPOSE_FILE_LOCAL="docker-compose.local.yml"
readonly COMPOSE_FILE_AZURE="deploy/docker-compose.azure.yml"
readonly MEDIA_ROOT="${APP_ROOT}/media"
readonly OPENAI_ENDPOINT="${COGENTREX_OPENAI_ENDPOINT:-https://cogentrex.services.ai.azure.com/openai/v1}"
readonly OPENAI_MODEL="${COGENTREX_OPENAI_MODEL:-DeepSeek-V4-Flash}"
readonly KEY_VAULT_NAME="${COGENTREX_KEY_VAULT_NAME:-}"
readonly PUBLIC_HOSTNAME="${COGENTREX_PUBLIC_HOSTNAME:-}"
readonly ACR_NAME="${COGENTREX_ACR_NAME:-}"
readonly ACR_LOGIN_SERVER="${COGENTREX_ACR_LOGIN_SERVER:-}"
readonly AZURE_SUBSCRIPTION_ID="${COGENTREX_AZURE_SUBSCRIPTION_ID:-}"
readonly LOCAL_BASE_URL="http://127.0.0.1:8080"
# Media marker used by install_learning_media_if_absent
export LEARNING_MEDIA_MARKER="cogentrex.learning-library/v1"
LAST_BACKUP=""

# ─── Helpers ────────────────────────────────────────────────────────────────────

log() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { log "FATAL: $*" >&2; exit 1; }

validate_sha() {
  local sha="$1"
  if [[ ! "$sha" =~ ^[0-9a-f]{40}$ ]]; then
    die "Invalid SHA: must be exactly 40 lowercase hex characters, got '${sha}'"
  fi
}

current_deployed_sha() {
  if [[ -f "$DEPLOY_STATE" ]]; then
    # shellcheck disable=SC1090
    (source "$DEPLOY_STATE" && printf '%s' "${COGENTREX_DEPLOYED_SHA:-}")
  fi
}

save_deploy_state() {
  local sha="$1"
  local previous_sha="${2:-}"
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  mkdir -p "$(dirname "$DEPLOY_STATE")"
  local tmp
  tmp="$(mktemp "${DEPLOY_STATE}.XXXXXX")"
  chmod 600 "$tmp"
  {
    printf 'COGENTREX_DEPLOYED_SHA=%s\n' "$sha"
    printf 'COGENTREX_PREVIOUS_SHA=%s\n' "$previous_sha"
    printf 'COGENTREX_LAST_BACKUP=%s\n' "$LAST_BACKUP"
    printf 'COGENTREX_DEPLOY_TIMESTAMP=%s\n' "$ts"
    printf 'COGENTREX_COMPOSE_PROJECT=%s\n' "$COMPOSE_PROJECT"
  } > "$tmp"
  mv -f "$tmp" "$DEPLOY_STATE"
  chmod 600 "$DEPLOY_STATE"
}

# ─── Clone / Fetch ──────────────────────────────────────────────────────────────

ensure_repo() {
  local sha="$1"
  local repo_dir="${APP_ROOT}/repo"

  if [[ -d "${repo_dir}/.git" ]]; then
    log "Fetching latest from origin..."
    git -C "$repo_dir" fetch origin --prune
  else
    log "Cloning repository..."
    git clone "$REPO_URL" "$repo_dir"
  fi

  log "Checking out immutable SHA ${sha}..."
  git -C "$repo_dir" checkout --detach --force "$sha"
  git -C "$repo_dir" submodule update --init --recursive
}

# ─── Learning Media ─────────────────────────────────────────────────────────────

install_learning_media_if_absent() {
  local marker_file="${MEDIA_ROOT}/.cogentrex-learning-library"
  if [[ -f "$marker_file" ]]; then
    log "Learning media already installed."
  else
    local repo_dir="${APP_ROOT}/repo"
    local release_script="${repo_dir}/scripts/learning-media-release.py"
    local manifest="${repo_dir}/docs/visual-learning/release-manifest.json"
    [[ -f "$release_script" && -f "$manifest" ]] || die "Learning media installer or manifest missing"
    log "Installing checksummed learning media release..."
    python3 "$release_script" install --target "$MEDIA_ROOT" --manifest "$manifest"
  fi

  # Run Command executes as root, while the backend runs unprivileged. The bind
  # mount remains read-only in Compose; host files only need read/traverse access.
  chmod -R u+rwX,go+rX "$MEDIA_ROOT"
}

# ─── Protected Env Generation ───────────────────────────────────────────────────

set_env_value() {
  local key="$1"
  local value="$2"
  python3 - "$COMPOSE_ENV_FILE" "$key" "$value" <<'PY'
from pathlib import Path
import os
import sys

path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
if "\n" in value or "\r" in value:
    raise SystemExit("environment value contains a newline")
lines = path.read_text(encoding="utf-8").splitlines()
lines = [line for line in lines if not line.startswith(f"{key}=")]
lines.append(f"{key}={value}")
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
os.chmod(tmp, 0o600)
tmp.replace(path)
PY
}

generate_env() {
  local image_tag="$1"
  local repo_dir="${APP_ROOT}/repo"
  local env_gen="${repo_dir}/scripts/generate-local-env.py"

  if [[ ! -f "$env_gen" ]]; then
    die "Environment generator not found at ${env_gen}"
  fi

  # Generate secret material only once. Rewriting the file would rotate keys and
  # make retained encrypted data unreadable.
  if [[ ! -f "$COMPOSE_ENV_FILE" ]]; then
    touch "$COMPOSE_ENV_FILE"
    chmod 600 "$COMPOSE_ENV_FILE"
    python3 "$env_gen" "$COMPOSE_ENV_FILE" --learning-media-root "$MEDIA_ROOT"
  else
    log "Retaining existing protected environment and encryption material."
  fi

  set_env_value COGENTREX_LLM_PROVIDER openai
  set_env_value COGENTREX_LOCAL_PORT 8080
  set_env_value COGENTREX_LLM_AUTH_MODE azure_identity
  set_env_value COGENTREX_LLM_BASE_URL "$OPENAI_ENDPOINT"
  set_env_value COGENTREX_LLM_MODEL "$OPENAI_MODEL"
  set_env_value COGENTREX_LLM_API_KEY ""
  set_env_value COGENTREX_RUNTIME_MODE live-foundry
  set_env_value COGENTREX_OPENAI_NATIVE_TOOLS_ENABLED true
  set_env_value COGENTREX_VERIFIER_ENABLED true
  set_env_value COGENTREX_VERIFIER_MODEL "$OPENAI_MODEL"
  set_env_value COGENTREX_AGENT_RUN_BUDGET_USD 0.25
  set_env_value COGENTREX_AGENT_PROJECT_BUDGET_USD 10.00
  set_env_value COGENTREX_RATE_LIMIT_AUTH_REQUESTS 10
  set_env_value COGENTREX_RATE_LIMIT_CHAT_REQUESTS 6
  set_env_value COGENTREX_OTEL_CAPTURE_MESSAGE_CONTENT false
  set_env_value COGENTREX_OTEL_COLLECTOR_CONFIG_FILE "${APP_ROOT}/repo/deploy/otel-collector.azure.yml"
  set_env_value COGENTREX_ACR_LOGIN_SERVER "$ACR_LOGIN_SERVER"
  set_env_value COGENTREX_IMAGE_TAG "$image_tag"

  if [[ -n "$KEY_VAULT_NAME" ]]; then
    log "Loading Application Insights configuration through VM managed identity."
    az login --identity --allow-no-subscriptions --output none
    [[ -n "$AZURE_SUBSCRIPTION_ID" ]] || die "Azure subscription ID is required"
    az account set --subscription "$AZURE_SUBSCRIPTION_ID"
    local app_insights
    for attempt in {1..18}; do
      app_insights="$(az keyvault secret show \
        --vault-name "$KEY_VAULT_NAME" \
        --name applicationinsights-connection-string \
        --query value -o tsv 2>/dev/null || true)"
      [[ -n "$app_insights" ]] && break
      log "Waiting for Key Vault RBAC propagation (${attempt}/18)..."
      sleep 10
    done
    [[ -n "$app_insights" ]] || die "Application Insights configuration is empty"
    set_env_value APPLICATIONINSIGHTS_CONNECTION_STRING "$app_insights"
  fi
  chmod 600 "$COMPOSE_ENV_FILE"
}

# ─── Backup ─────────────────────────────────────────────────────────────────────

pg_backup() {
  local sha="$1"
  local ts
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  local dump_file="${BACKUP_DIR}/cogentrex-${sha:0:12}-${ts}.dump"

  mkdir -p "$BACKUP_DIR"
  chmod 700 "$BACKUP_DIR"

  local repo_dir="${APP_ROOT}/repo"
  local backup_script="${repo_dir}/scripts/local-backup.sh"

  [[ -f "$backup_script" ]] || die "Canonical backup script missing"
  log "Running mandatory pg_dump backup via canonical script..."
  bash "$backup_script" "$COMPOSE_PROJECT" "$COMPOSE_ENV_FILE" "$dump_file"
  [[ -s "$dump_file" && -s "${dump_file}.sha256" ]] || die "Backup evidence is incomplete"
  LAST_BACKUP="$dump_file"
  log "Backup saved: ${dump_file}"
}

# ─── Docker Compose Update ──────────────────────────────────────────────────────

compose_update() {
  local repo_dir="${APP_ROOT}/repo"
  local compose=(docker compose --env-file "$COMPOSE_ENV_FILE"
    -f "${repo_dir}/${COMPOSE_FILE_LOCAL}"
    -f "${repo_dir}/${COMPOSE_FILE_AZURE}"
    -p "$COMPOSE_PROJECT")

  [[ -n "$ACR_NAME" && -n "$ACR_LOGIN_SERVER" ]] || die "ACR configuration is required"
  az login --identity --allow-no-subscriptions --output none
  [[ -n "$AZURE_SUBSCRIPTION_ID" ]] || die "Azure subscription ID is required"
  az account set --subscription "$AZURE_SUBSCRIPTION_ID"
  az acr login --name "$ACR_NAME" --output none
  log "Pulling immutable application images..."
  "${compose[@]}" pull

  log "Starting services (preserving volumes)..."
  COGENTREX_LOCAL_PORT=8080 "${compose[@]}" up -d --wait --remove-orphans --no-build
}

configure_caddy() {
  [[ -n "$PUBLIC_HOSTNAME" ]] || die "COGENTREX_PUBLIC_HOSTNAME is required"
  local repo_dir="${APP_ROOT}/repo"
  local source_config="${repo_dir}/deploy/Caddyfile.azure"
  local caddy_image="caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d"
  [[ -f "$source_config" ]] || die "Caddy configuration missing"

  install -d -o root -g root -m 0755 /etc/caddy
  install -o root -g root -m 0644 "$source_config" /etc/caddy/Caddyfile
  docker pull "$caddy_image"
  docker run --rm \
    -e COGENTREX_PUBLIC_HOSTNAME="$PUBLIC_HOSTNAME" \
    -v /etc/caddy/Caddyfile:/etc/caddy/Caddyfile:ro \
    "$caddy_image" validate --config /etc/caddy/Caddyfile
  docker rm -f cogentrex-caddy >/dev/null 2>&1 || true
  docker run -d \
    --name cogentrex-caddy \
    --restart unless-stopped \
    --network host \
    -e COGENTREX_PUBLIC_HOSTNAME="$PUBLIC_HOSTNAME" \
    -v /etc/caddy/Caddyfile:/etc/caddy/Caddyfile:ro \
    -v cogentrex-caddy-data:/data \
    -v cogentrex-caddy-config:/config \
    "$caddy_image"
}

# ─── Health Checks ──────────────────────────────────────────────────────────────

wait_for_health() {
  local base_url="$1"
  local max_wait="${2:-120}"
  local endpoints=("healthz" "readyz")

  for endpoint in "${endpoints[@]}"; do
    log "Waiting for /${endpoint}..."
    local elapsed=0
    while (( elapsed < max_wait )); do
      if curl --fail --silent --show-error "${base_url}/${endpoint}" >/dev/null 2>&1; then
        log "/${endpoint} is healthy."
        break
      fi
      sleep 2
      elapsed=$(( elapsed + 2 ))
    done
    if (( elapsed >= max_wait )); then
      die "/${endpoint} did not become healthy within ${max_wait}s"
    fi
  done
}

check_health_details() {
  local base_url="$1"

  log "Verifying /healthz response..."
  curl --fail --silent --show-error "${base_url}/healthz" | python3 -c '
import json, sys
d = json.load(sys.stdin)
assert d["status"] == "alive", f"healthz status: {d['status']}"
print("  healthz: alive, provider=" + d.get("llm_provider", "?") + " model=" + d.get("llm_model", "?"))
'

  log "Verifying /readyz response..."
  curl --fail --silent --show-error "${base_url}/readyz" | python3 -c '
import json, sys
d = json.load(sys.stdin)
deps = d["dependencies"]
assert d["status"] == "ready", f"readyz status: {d['status']}"
assert deps["conversation_repository"] == "up"
assert deps["rate_limiter"]["status"] == "up"
print("  readyz: ready, db=up, redis=up")
'
}

check_media() {
  local base_url="$1"
  [[ -f "${MEDIA_ROOT}/.cogentrex-learning-library" ]] || die "Learning media marker missing"
  [[ -s "${MEDIA_ROOT}/catalog.json" ]] || die "Learning media catalog missing"
  log "Checking /learn route and installed media catalog..."
  curl --fail --silent --show-error "${base_url}/learn" >/dev/null
  python3 - "$MEDIA_ROOT/catalog.json" <<'PY'
import json
import sys
from pathlib import Path

catalog = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
artifacts = [artifact for pack in catalog.get("packs", []) for artifact in pack.get("artifacts", [])]
if not artifacts:
    raise SystemExit("learning media catalog has no artifacts")
for artifact in artifacts:
    path = Path(sys.argv[1]).parent / artifact["file"]
    if not path.is_file():
        raise SystemExit(f"missing learning artifact: {artifact['id']}")
print(f"learning_media_artifacts={len(artifacts)}")
PY
}

check_sandbox() {
  local repo_dir="${APP_ROOT}/repo"
  local compose=(docker compose --env-file "$COMPOSE_ENV_FILE"
    -f "${repo_dir}/${COMPOSE_FILE_LOCAL}" -p "$COMPOSE_PROJECT")

  log "Checking sandbox container controls..."
  local sandbox_id
  sandbox_id="$("${compose[@]}" ps -q sandbox-runner)"
  [[ -n "$sandbox_id" ]] || die "Sandbox container is not running"
  [[ "$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$sandbox_id")" == "none" ]] \
    || die "Sandbox network mode is not none"
  [[ "$(docker inspect -f '{{.HostConfig.ReadonlyRootfs}}' "$sandbox_id")" == "true" ]] \
    || die "Sandbox root filesystem is not read-only"
  if "${compose[@]}" exec -T sandbox-runner python3 -c \
    "import socket; socket.create_connection(('8.8.8.8', 53), timeout=3)" 2>/dev/null; then
    die "Sandbox network isolation FAILED: egress should be denied"
  else
    log "  Sandbox network isolation: verified (egress denied)."
  fi
}

# ─── Rollback ───────────────────────────────────────────────────────────────────

rollback() {
  local previous_sha="$1"
  if [[ -z "$previous_sha" ]]; then
    die "No previous SHA available for rollback."
  fi
  log "ROLLING BACK to SHA ${previous_sha}..."
  ensure_repo "$previous_sha"
  set_env_value COGENTREX_IMAGE_TAG "$previous_sha"
  if [[ -n "$LAST_BACKUP" && -s "$LAST_BACKUP" ]]; then
    local repo_dir="${APP_ROOT}/repo"
    local compose=(docker compose --env-file "$COMPOSE_ENV_FILE"
      -f "${repo_dir}/${COMPOSE_FILE_LOCAL}" -p "$COMPOSE_PROJECT")
    "${compose[@]}" stop gateway frontend backend
    ALLOW_REPLACE=1 bash "${repo_dir}/scripts/local-restore.sh" \
      "$COMPOSE_PROJECT" "$COMPOSE_ENV_FILE" "$LAST_BACKUP"
  fi
  compose_update
  wait_for_health "$LOCAL_BASE_URL" 120
  save_deploy_state "$previous_sha"
  log "Rollback to ${previous_sha} complete."
}

# ─── Main ───────────────────────────────────────────────────────────────────────

main() {
  local target_sha="${1:-}"
  if [[ -z "$target_sha" ]]; then
    die "Usage: deploy-vm.sh <40-char-SHA> [--repo URL]"
  fi
  shift

  # Parse optional args
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --repo) COGENTREX_REPO_URL="$2"; shift 2 ;;
      *) die "Unknown argument: $1" ;;
    esac
  done

  validate_sha "$target_sha"

  cloud-init status --wait >/dev/null
  command -v docker >/dev/null || die "Docker is not installed"
  docker compose version >/dev/null || die "Docker Compose plugin is unavailable"

  local previous_sha
  previous_sha="$(current_deployed_sha)"

  if [[ "$previous_sha" == "$target_sha" ]]; then
    log "SHA ${target_sha} is already deployed. Re-running health checks..."
    wait_for_health "$LOCAL_BASE_URL" 60
    check_health_details "$LOCAL_BASE_URL"
    log "Deployment verified."
    exit 0
  fi

  log "Deploying SHA ${target_sha}..."
  [[ -n "$previous_sha" ]] && log "Previous SHA: ${previous_sha}"

  # Persistent directories
  mkdir -p "$TMPDIR_PERSIST" "$STATE_DIR" "$BACKUP_DIR"
  chmod 700 "$TMPDIR_PERSIST" "$STATE_DIR" "$BACKUP_DIR"
  export TMPDIR="$TMPDIR_PERSIST"
  export XDG_STATE_HOME="$STATE_DIR"

  # Step 1: Back up the running revision before changing the checkout.
  if [[ -n "$previous_sha" ]]; then
    [[ -f "$COMPOSE_ENV_FILE" ]] || die "Retained deployment is missing its protected env"
    pg_backup "$previous_sha"
  fi

  # Step 2: Clone/fetch and checkout the immutable target.
  ensure_repo "$target_sha"

  # Step 3: Install learning media if absent.
  install_learning_media_if_absent

  # Step 4: Generate or retain the protected environment.
  generate_env "$target_sha"

  # Step 5: Docker compose update (preserving volumes)
  if ! compose_update; then
    log "ERROR: Compose update failed."
    if [[ -n "$previous_sha" ]]; then
      rollback "$previous_sha"
    fi
    exit 1
  fi

  # Step 6: Health checks
  if ! wait_for_health "$LOCAL_BASE_URL" 120; then
    log "ERROR: Health checks failed after deployment."
    if [[ -n "$previous_sha" ]]; then
      rollback "$previous_sha"
    fi
    exit 1
  fi

  if ! check_health_details "$LOCAL_BASE_URL"; then
    log "ERROR: Detailed health checks failed."
    if [[ -n "$previous_sha" ]]; then
      rollback "$previous_sha"
    fi
    exit 1
  fi

  # Step 7: Media and sandbox are required parity gates.
  check_media "$LOCAL_BASE_URL"
  check_sandbox

  # Step 8: Configure the public HTTPS edge only after local acceptance passes.
  configure_caddy

  # Step 9: Record deployment
  save_deploy_state "$target_sha" "$previous_sha"

  log "Deployment of ${target_sha} complete."
  log "Previous SHA: ${previous_sha:-none}"
  log "Public URL: https://${PUBLIC_HOSTNAME}"
}

main "$@"
