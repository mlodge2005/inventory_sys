#!/usr/bin/env bash
# Local health check. Exit 0 only when /api/v1/health reports status ok.
set -euo pipefail
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$SOURCE_DIR/scripts/lib/common.sh"
prefix_paths
[[ -f "$ENV_FILE" ]] || die "Missing $ENV_FILE."
port="$(env_value INVENTORY_PORT)"
port="${port:-$DEFAULT_PORT}"
if ! health_once "$port"; then
  log "Health check failed on port $port."
  log "  journalctl -u $SERVICE_NAME -n 80 --no-pager"
  exit 1
fi
python_bin="$VENV_DIR/bin/python"
[[ -x "$python_bin" ]] || python_bin="$(command -v python3)"
if [[ -f "$DB_PATH" ]]; then
  result="$(PYTHONPATH="${INVENTORY_PYTHONPATH:-$CURRENT_LINK/backend}" INVENTORY_DATABASE_PATH="$DB_PATH" INVENTORY_ENVIRONMENT=production "$python_bin" -m app.maintenance integrity --database "$DB_PATH")"
  [[ "$result" == "ok" ]] || die "Database integrity check returned: $result"
fi
log "healthy on port $port"
