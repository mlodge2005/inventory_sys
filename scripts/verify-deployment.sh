#!/usr/bin/env bash
# Checks this installation only. It does not restart or inspect unrelated services.
set -euo pipefail
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$SOURCE_DIR/scripts/lib/common.sh"
prefix_paths
fail=0
note() { printf '%s\n' "$*"; }

[[ -f "$ENV_FILE" ]] || { note "missing $ENV_FILE"; fail=1; }
[[ -L "$CURRENT_LINK" || -d "$CURRENT_LINK" ]] || { note "missing $CURRENT_LINK"; fail=1; }
[[ -x "$BIN_DIR/inventory" ]] || { note "missing $BIN_DIR/inventory"; fail=1; }
[[ -f "$UNIT_DIR/$SERVICE_NAME" ]] || { note "missing unit $UNIT_DIR/$SERVICE_NAME"; fail=1; }
if [[ -f "$UNIT_DIR/$SERVICE_NAME" ]] && grep -q 'cyberdeck-inventory' "$UNIT_DIR/$SERVICE_NAME"; then
  note "unit file is $SERVICE_NAME"
fi
if [[ "$fail" -eq 0 ]]; then
  "$SOURCE_DIR/scripts/healthcheck.sh"
fi
note "Verification does not modify firewall rules, Tailscale, or other websites."
exit "$fail"
