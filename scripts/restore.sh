#!/usr/bin/env bash
# Restore a backup. Stops writers, keeps the current database as a safety copy.
# Usage: sudo ./scripts/restore.sh /path/to/inventory.db --yes
set -euo pipefail
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$SOURCE_DIR/scripts/lib/common.sh"
prefix_paths
require_root_if_needed
backup="${1:-}"
confirm="${2:-}"
[[ -n "$backup" ]] || die "Usage: $0 BACKUP_FILE --yes"
[[ "$confirm" == "--yes" ]] || die "Refusing to replace the live database without --yes. The current database is kept as a safety copy when you confirm."
[[ -f "$backup" ]] || die "Backup does not exist: $backup"
acquire_lock
stop_service
python_bin="$VENV_DIR/bin/python"
[[ -x "$python_bin" ]] || python_bin="$(command -v python3)"
PYTHONPATH="${INVENTORY_PYTHONPATH:-$CURRENT_LINK/backend}" \
  INVENTORY_DATABASE_PATH="$DB_PATH" \
  INVENTORY_ENVIRONMENT=production \
  "$python_bin" -m app.maintenance restore --backup "$backup" --database "$DB_PATH"
fix_data_permissions
start_service || true
port="$(env_value INVENTORY_PORT)"
port="${port:-$DEFAULT_PORT}"
if ! wait_for_health "$port"; then
  log "Restore finished but the health check failed. The previous database was kept beside $DB_PATH as a before-restore snapshot."
  log "Diagnostics: journalctl -u $SERVICE_NAME -n 80 --no-pager"
  exit 1
fi
log "Restore complete. A safety copy of the previous database remains in $VAR_DIR."
