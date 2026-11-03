#!/usr/bin/env bash
# Remove the application service and program files.
# The database and backups in /var/lib/cyberdeck-inventory are kept.
# Delete them only with: sudo ./scripts/uninstall.sh --purge --yes
set -euo pipefail
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$SOURCE_DIR/scripts/lib/common.sh"
prefix_paths
require_root_if_needed
stop_service
bin="$(systemctl_bin)"
if [[ -n "$bin" && "$ROOTLESS" == 0 ]]; then
  "$bin" disable "$SERVICE_NAME" || true
  rm -f "$UNIT_DIR/$SERVICE_NAME"
  "$bin" daemon-reload || true
else
  rm -f "$UNIT_DIR/$SERVICE_NAME"
fi
rm -f "$BIN_DIR/inventory"
rm -rf "$OPT_DIR"
if [[ "${1:-}" == "--purge" ]]; then
  [[ "${2:-}" == "--yes" ]] || die "Purge keeps nothing. Re-run with --purge --yes to delete $VAR_DIR and $ENV_FILE."
  rm -rf "$VAR_DIR"
  rm -f "$ENV_FILE"
  log "Purged $VAR_DIR and $ENV_FILE."
else
  log "Removed the service and program files. Database and backups remain in $VAR_DIR."
  log "Configuration remains at $ENV_FILE."
fi
