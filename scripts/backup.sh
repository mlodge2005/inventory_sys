#!/usr/bin/env bash
# Consistent SQLite backup via the backup API. Safe to run while the service is up.
set -euo pipefail
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$SOURCE_DIR/scripts/lib/common.sh"
prefix_paths
[[ -f "$ENV_FILE" ]] || die "Missing $ENV_FILE. Install the application first."
[[ -f "$DB_PATH" ]] || die "Database does not exist: $DB_PATH"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
dest="${1:-$BACKUP_DIR/inventory-$stamp.db}"
mkdir -p "$(dirname "$dest")"
python_bin="$VENV_DIR/bin/python"
[[ -x "$python_bin" ]] || python_bin="$(command -v python3)"
PYTHONPATH="${INVENTORY_PYTHONPATH:-$CURRENT_LINK/backend}" \
  INVENTORY_DATABASE_PATH="$DB_PATH" \
  INVENTORY_ENVIRONMENT=production \
  "$python_bin" -m app.maintenance backup --database "$DB_PATH" --dest "$dest"
printf 'Backup written to %s\n' "$dest"
printf 'Metadata: %s.json\n' "$dest"
