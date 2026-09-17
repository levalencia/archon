#!/usr/bin/env bash
# rollback-vm.sh – Roll back to the previously deployed SHA on the Azure VM.
#
# Usage: rollback-vm.sh [--force SHA]
#
# Without --force, reads the previous SHA from deploy state and invokes deploy-vm.sh.
# With --force, deploys the given SHA directly.
set -Eeuo pipefail
shopt -s inherit_errexit

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
readonly APP_ROOT="${COGENTREX_APP_ROOT:-/opt/cogentrex}"
readonly STATE_DIR="${XDG_STATE_HOME:-$APP_ROOT/.state}"
readonly DEPLOY_STATE="${STATE_DIR}/deploy.env"

log() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { log "FATAL: $*" >&2; exit 1; }

main() {
  local target_sha=""
  local force=false

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --force)
        force=true
        target_sha="${2:-}"
        [[ -n "$target_sha" ]] || die "--force requires a SHA argument"
        shift 2
        ;;
      -h|--help)
        printf 'Usage: rollback-vm.sh [--force SHA]\n'
        exit 0
        ;;
      *)
        die "Unknown argument: $1"
        ;;
    esac
  done

  if [[ "$force" == "true" ]]; then
    log "Force rollback to SHA ${target_sha}"
  else
    # Read the current deployed SHA from state
    if [[ ! -f "$DEPLOY_STATE" ]]; then
      die "No deploy state found at ${DEPLOY_STATE}; cannot determine previous SHA."
    fi

    local current_sha
    # shellcheck disable=SC1090
    current_sha="$(source "$DEPLOY_STATE" && printf '%s' "${COGENTREX_DEPLOYED_SHA:-}")"
    [[ -n "$current_sha" ]] || die "No deployed SHA found in state file."

    # Look for backup metadata to find previous SHA
    local backup_dir="${APP_ROOT}/backups"
    local latest_backup
    latest_backup="$(find "$backup_dir" -name '*.metadata.json' -type f 2>/dev/null \
      | sort -r | head -1)"

    if [[ -n "$latest_backup" ]]; then
      target_sha="$(python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    m = json.load(f)
# Extract SHA prefix from backup filename
import os
base = os.path.basename(sys.argv[1])
# Format: cogentrex-<sha12>-<ts>.dump.metadata.json
parts = base.split('-')
if len(parts) >= 2:
    sha_prefix = parts[1]
    print(sha_prefix)
else:
    print('')
" "$latest_backup")"
    fi

    if [[ -z "$target_sha" || ${#target_sha} -ne 40 ]]; then
      die "Cannot determine previous SHA from backups. Use --force SHA to specify."
    fi

    log "Rolling back from ${current_sha} to ${target_sha}"
  fi

  # Delegate to deploy-vm.sh
  exec bash "${SCRIPT_DIR}/deploy-vm.sh" "$target_sha"
}

main "$@"
